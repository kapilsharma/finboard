"""M3a pure pieces: the vote, trigram similarity, tracing off, and the evaluation harness."""

from __future__ import annotations

import importlib
import os
import uuid
from pathlib import Path

import pytest

from finboard.ai import evaluation, force_tracing_off
from finboard.ai.suggest import SHARPNESS, Neighbour, vote
from finboard.ai.trigram import similarity, trigrams

A, B, C, D = (uuid.uuid4() for _ in range(4))


def n(category: uuid.UUID, sim: float) -> Neighbour:
    return Neighbour(uuid.uuid4(), category, sim)


def test_vote_ranks_by_weighted_share() -> None:
    result = vote([n(A, 0.9), n(A, 0.8), n(B, 0.7)], sharpness=1.0)
    assert [s.category_id for s in result] == [A, B]
    assert result[0].confidence == pytest.approx(1.7 / 2.4, abs=1e-3)
    assert result[0].examples[0].similarity == 0.9  # closest first


def test_sharpness_lets_one_close_neighbour_beat_many_loose_ones() -> None:
    neighbours = [n(A, 0.95), *(n(B, 0.6) for _ in range(4))]
    assert vote(neighbours, sharpness=1.0)[0].category_id == B
    assert vote(neighbours, sharpness=8.0)[0].category_id == A


def test_nothing_alike_gives_no_suggestion() -> None:
    assert vote([n(A, 0.2), n(B, 0.1)], min_similarity=0.25) == []
    assert vote([]) == []


def test_floor_limit_and_examples() -> None:
    neighbours = [*(n(A, 0.9) for _ in range(5)), n(B, 0.5), n(C, 0.5), n(D, 0.1)]
    result = vote(neighbours, sharpness=1.0, floor=0.0, limit=3)
    assert len(result) == 3
    assert len(result[0].examples) == 3  # at most 3 examples each
    assert [s.category_id for s in vote(neighbours, sharpness=1.0)] == [A]  # B, C under 20 %


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("cat", {"  c", " ca", "cat", "at "}),
        ("A-1", {"  a", " a ", "  1", " 1 "}),
        ("", set()),
    ],
)
def test_trigrams_match_pg_trgm(text: str, expected: set[str]) -> None:
    assert trigrams(text) == expected


def test_similarity() -> None:
    assert similarity("swiggy", "swiggy") == 1.0
    assert similarity("swiggy", "") == 0.0
    assert 0 < similarity("swiggy order", "swigy order") < 1


def test_tracing_forced_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2-canary")
    importlib.reload(importlib.import_module("finboard.ai"))
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
    assert "LANGSMITH_API_KEY" not in os.environ
    force_tracing_off()


def test_evaluation_dataset_is_deterministic_and_has_no_exact_repeats() -> None:
    labelled, queries = evaluation.dataset(11)
    assert evaluation.dataset(11) == (labelled, queries)
    seen = {e.text for e in labelled}
    assert queries and not any(q.text in seen for q in queries)
    assert {q.variant for q in queries} >= {"typo", "truncated", "other_handle"}


def test_trigram_baseline_is_well_above_chance() -> None:
    score = evaluation.evaluate("trigram", evaluation.trigram_matrix, 11, sharpness=3)
    assert score.top1 > 0.6  # 8 categories: chance is 0.125
    assert 0 < score.covered <= 1


def test_default_model_beats_trigram_offline() -> None:
    """The ROADMAP M3a verdict, re-checked whenever the model is on disk (no network here)."""
    from finboard.ai import embeddings
    from finboard.core.config import get_settings

    settings = get_settings()
    cache = Path(settings.model_dir)
    if not cache.is_absolute():
        cache = Path(__file__).parents[2] / cache
    if not embeddings.is_ready(settings.embed_model, cache):
        pytest.skip("embedding model not fetched (finboard ai fetch-model)")

    def embed(texts: list[str]) -> list[list[float]]:
        return embeddings.embed(texts, model=settings.embed_model, cache_dir=cache)

    results = {
        r.method: r
        for r in evaluation.compare(
            {
                "trigram": evaluation.trigram_matrix,
                "embedding": evaluation.embedding_matrix_for(embed),
            }
        )
    }
    assert results["embedding"].mean > results["trigram"].mean


def test_trigram_parameters_match_the_evaluation() -> None:
    """The served sharpness and cut-off are the ones the evaluation picks."""
    from finboard.services.ai import MIN_SIMILARITY

    (result,) = evaluation.compare({"trigram": evaluation.trigram_matrix})
    assert result.sharpness == SHARPNESS["trigram"]
    assert result.min_similarity == MIN_SIMILARITY["trigram"]


def test_unseen_merchants_are_new() -> None:
    labelled, _ = evaluation.dataset(7)
    known = {e.merchant for e in labelled}
    assert not known & set(evaluation.UNSEEN_MERCHANTS)
    assert len(evaluation.unseen(7)) == 2 * len(evaluation.UNSEEN_MERCHANTS)
