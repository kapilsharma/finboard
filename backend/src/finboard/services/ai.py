"""Optional AI features (ARCHITECTURE §18, ADR-0030): settings, category suggestions (M3a).

Two levels of switch: the operator makes a feature *available* (environment), each user
turns it *on* (Settings > AI, `user_setting` keys below, default off). AI libraries are
imported lazily, so the app runs without the `ai` extra and reports the features as
unavailable.

Suggestions never change anything: accepting one is an ordinary manual categorisation.
"""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import structlog

from finboard.ai.suggest import SHARPNESS, K, vote
from finboard.ai.text import embedding_key, match_text
from finboard.core.config import Settings
from finboard.db.models import Category, Job
from finboard.db.repos import NeighbourRow
from finboard.db.uow import UnitOfWork
from finboard.domain.errors import AiFeatureOff, Conflict, FinboardError, NotFound
from finboard.services.jobs import JobQueue, JobService

log = structlog.get_logger(__name__)

SUGGESTIONS_KEY = "ai.suggestions"
ASK_KEY = "ai.ask"
EMBED_TASK = "ai.embed"  # after a commit: embed what isn't yet
EMBED_ALL_TASK = "ai.embed_all"  # backfill, and re-embed after a model change
EMBED_BATCH = 256
# Below these, a neighbour doesn't vote, so a merchant unlike anything categorised gets no
# suggestion. Calibrated with never-seen merchants for the default model (docs/ai-eval.md);
# trigram similarity can't tell them apart, so it never abstains.
MIN_SIMILARITY = {"embedding": 0.45, "trigram": 0.0}

Method = Literal["embedding", "trigram"]


@dataclass(frozen=True, slots=True)
class AiConfig:
    suggestions: bool
    suggest_method: Literal["auto", "embedding", "trigram"]
    embed_model: str
    model_dir: Path
    ask: Literal["off", "gemini", "ollama"]
    ask_sql: bool
    ai_model: str

    @classmethod
    def from_settings(cls, s: Settings) -> AiConfig:
        return cls(
            suggestions=s.ai_suggestions,
            suggest_method=s.ai_suggest_method,
            embed_model=s.embed_model,
            model_dir=Path(s.model_dir),
            ask=s.ai_ask,
            ask_sql=s.ai_ask_sql,
            ai_model=s.ai_model if s.ai_ask == "gemini" else s.ollama_model,
        )

    @property
    def embedding_key(self) -> str:
        return embedding_key(self.embed_model)

    @property
    def uses_embeddings(self) -> bool:
        return self.suggestions and self.suggest_method != "trigram"


def extra_installed(module: str = "fastembed") -> bool:
    return importlib.util.find_spec(module) is not None


@dataclass(frozen=True, slots=True)
class AiStatus:
    suggestions_available: bool
    suggestions_enabled: bool
    suggest_method: str
    embed_model: str
    embedded: int
    transactions: int
    ask_available: bool
    ask_enabled: bool
    ask_provider: str
    ask_sql: bool


class AiSettingsService:
    def __init__(self, uow: UnitOfWork, config: AiConfig, queue: JobQueue) -> None:
        self.uow = uow
        self.config = config
        self.jobs = JobService(uow, queue)

    def ask_available(self) -> bool:
        return self.config.ask != "off" and extra_installed("langgraph")

    async def enabled(self, key: str) -> bool:
        return (await self.uow.settings.all()).get(key) is True

    async def status(self) -> AiStatus:
        stored = await self.uow.settings.all()
        embedded, total = await self.uow.embeddings.counts(self.config.embedding_key)
        return AiStatus(
            suggestions_available=self.config.suggestions,
            suggestions_enabled=self.config.suggestions and stored.get(SUGGESTIONS_KEY) is True,
            suggest_method=self.config.suggest_method,
            embed_model=self.config.embed_model,
            embedded=embedded,
            transactions=total,
            ask_available=self.ask_available(),
            ask_enabled=self.ask_available() and stored.get(ASK_KEY) is True,
            ask_provider=self.config.ask,
            ask_sql=self.config.ask_sql,
        )

    async def update(self, *, suggestions: bool | None = None, ask: bool | None = None) -> AiStatus:
        if suggestions and not self.config.suggestions:
            raise Conflict("Category suggestions aren't available on this server")
        if ask and not self.ask_available():
            raise Conflict("Ask Finboard isn't available on this server")
        if suggestions is not None:
            await self.uow.settings.set(SUGGESTIONS_KEY, suggestions)
        if ask is not None:
            await self.uow.settings.set(ASK_KEY, ask)
        if suggestions and self.config.uses_embeddings:
            await self.jobs.submit(EMBED_ALL_TASK)  # commits too
        else:
            await self.uow.commit()
        return await self.status()


# ---------------------------------------------------------------- suggestions


@dataclass(frozen=True, slots=True)
class CategorySuggestion:
    category: Category
    confidence: float
    examples: list[NeighbourRow]


@dataclass(frozen=True, slots=True)
class Suggestions:
    method: Method
    items: list[CategorySuggestion]


class SuggestionService:
    def __init__(self, uow: UnitOfWork, config: AiConfig) -> None:
        self.uow = uow
        self.config = config

    async def suggest(self, txn_id: uuid.UUID) -> Suggestions:
        if (
            not self.config.suggestions
            or (await self.uow.settings.all()).get(SUGGESTIONS_KEY) is not True
        ):
            raise AiFeatureOff("Category suggestions are off (Settings > AI)")
        txn = await self.uow.txns.get(txn_id)
        if txn is None:
            raise NotFound("Transaction not found")
        method: Method
        if not match_text(txn.description_norm):  # no merchant words: nothing to compare
            return Suggestions(
                "trigram" if self.config.suggest_method == "trigram" else "embedding", []
            )
        if self.config.suggest_method == "trigram":
            method = "trigram"
        elif await self.uow.embeddings.has_embedding(txn_id, self.config.embedding_key):
            method = "embedding"
        elif self.config.suggest_method == "embedding":
            return Suggestions("embedding", [])  # not embedded yet
        else:
            method = "trigram"  # auto: until this transaction has an embedding
        rows = (
            await self.uow.embeddings.neighbours_by_embedding(txn_id, self.config.embedding_key, K)
            if method == "embedding"
            else await self.uow.embeddings.neighbours_by_trigram(txn_id, K)
        )
        from finboard.ai.suggest import Neighbour

        by_id = {r.txn_id: r for r in rows}
        ranked = vote(
            [Neighbour(r.txn_id, r.category_id, float(r.similarity)) for r in rows],
            sharpness=SHARPNESS[method],
            min_similarity=MIN_SIMILARITY[method],
        )
        categories = {c.id: c for c in await self.uow.categories.list()}
        return Suggestions(
            method,
            [
                CategorySuggestion(
                    categories[s.category_id], s.confidence, [by_id[e.txn_id] for e in s.examples]
                )
                for s in ranked
                if s.category_id in categories
            ],
        )


# ---------------------------------------------------------------- embedding (worker side)


class EmbeddingFailed(FinboardError):
    code = "embedding_failed"
    title = "Embedding failed"


class EmbeddingService:
    def __init__(self, uow: UnitOfWork, config: AiConfig) -> None:
        self.uow = uow
        self.config = config

    async def run(self, _job: Job) -> dict[str, Any]:
        """Embed every transaction without a current embedding, a batch per transaction.
        Only the merchant words of the normalised description are embedded (`ai.text`): no
        amounts, reference numbers or narration boilerplate."""
        from finboard.ai.embeddings import EmbeddingsUnavailable, embed

        if not self.config.uses_embeddings:
            return {"embedded": 0, "skipped": "suggestions use trigram similarity"}
        done = 0
        while True:
            batch = await self.uow.embeddings.to_embed(self.config.embedding_key, EMBED_BATCH)
            if not batch:
                break
            try:
                vectors = await asyncio.to_thread(
                    embed,
                    [match_text(text) or text for _, text in batch],
                    model=self.config.embed_model,
                    cache_dir=self.config.model_dir,
                )
            except EmbeddingsUnavailable as exc:
                raise EmbeddingFailed(str(exc)) from None
            await self.uow.embeddings.upsert(
                self.config.embedding_key,
                [(tid, v) for (tid, _), v in zip(batch, vectors, strict=True)],
            )
            await self.uow.commit()
            done += len(batch)
        log.info("ai.embedded", count=done, model=self.config.embed_model)
        return {"embedded": done, "model": self.config.embed_model}
