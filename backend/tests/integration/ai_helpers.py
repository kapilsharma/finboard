"""Helpers for the AI tests: an app with the features available, and a stand-in embedder.

The real embedding model is a download (`finboard ai fetch-model`), so CI uses a small
deterministic embedder: hashed character trigrams, unit length. Similar descriptions get
similar vectors, which is all the suggestion code relies on.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from finboard.ai import embeddings
from finboard.ai.trigram import trigrams
from finboard.auth import Principal
from finboard.core.config import Settings
from finboard.db.models import EMBEDDING_DIMENSIONS
from finboard.jobs import tasks
from finboard.main import create_app

from .conftest import TASKS, HeaderAuthBackend, RecordingJobQueue

TASKS.setdefault("ai.embed", tasks.embed)
TASKS.setdefault("ai.embed_all", tasks.embed_all)

API = "/api/v1"


def fake_embed(texts: Sequence[str], *, model: str, cache_dir: Path) -> list[list[float]]:
    del model, cache_dir
    out: list[list[float]] = []
    for text in texts:
        v = [0.0] * EMBEDDING_DIMENSIONS
        for gram in trigrams(text):
            h = int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=4).digest(), "big")
            v[h % EMBEDDING_DIMENSIONS] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        out.append([x / norm for x in v])
    return out


async def category_ids(client: httpx.AsyncClient, user: str = "alice") -> dict[str, str]:
    response = await client.get(f"{API}/categories", headers={"X-Test-User": user})
    assert response.status_code == 200
    return {c["name"]: c["id"] for c in response.json()["items"]}


async def categorise(
    client: httpx.AsyncClient, ids: Sequence[object], category_id: str, user: str = "alice"
) -> None:
    response = await client.post(
        f"{API}/transactions/bulk",
        json={"ids": [str(i) for i in ids], "category_id": category_id},
        headers={"X-Test-User": user},
    )
    assert response.status_code == 200, response.text


def _ai_settings(settings: Settings, method: str) -> Settings:
    return settings.model_copy(update={"ai_suggestions": True, "ai_suggest_method": method})


@pytest.fixture(params=["trigram", "auto"])
async def ai_app(
    request: pytest.FixtureRequest,
    settings: Settings,
    alice: Principal,
    bob: Principal,
    job_queue: RecordingJobQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[FastAPI]:
    ai = _ai_settings(settings, request.param)
    monkeypatch.setattr(tasks, "get_settings", lambda: ai)
    monkeypatch.setattr(embeddings, "embed", fake_embed)
    backend = HeaderAuthBackend({"alice": alice, "bob": bob}, default="alice")
    application = create_app(ai, auth_backend=backend, job_queue=job_queue)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def ai_client(ai_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ai_app),
        base_url="http://127.0.0.1",
        headers={"X-Finboard-Client": "1"},
    ) as c:
        yield c
