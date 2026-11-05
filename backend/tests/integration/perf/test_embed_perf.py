"""Performance budget (ROADMAP M3a): 5,000 transactions embedded in under 60 s on a laptop
CPU, with the worker under 600 MB. Runs the real `ai.embed_all` task body and the real model,
so it skips unless the model was fetched (`finboard ai fetch-model`)."""

from __future__ import annotations

import resource
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.ai import embeddings, evaluation
from finboard.ai.text import embedding_key
from finboard.auth import Principal
from finboard.core.config import Settings
from finboard.db.uow import unit_of_work
from finboard.jobs import tasks

from ..categorisation_helpers import account, add_txns
from ..conftest import RecordingJobQueue

pytestmark = pytest.mark.perf
TXNS = 5_000


async def test_embed_5k_within_budget(
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
    job_queue: RecordingJobQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_dir = Path(settings.model_dir)
    if not model_dir.is_absolute():
        model_dir = Path(__file__).parents[3] / model_dir
    if not embeddings.is_ready(settings.embed_model, model_dir):
        pytest.skip("embedding model not fetched (finboard ai fetch-model)")
    ai = settings.model_copy(update={"ai_suggestions": True, "model_dir": str(model_dir)})
    monkeypatch.setattr(tasks, "get_settings", lambda: ai)

    labelled, queries = evaluation.dataset(11)
    texts = [e.text for e in labelled + queries]
    acc = await account(sessionmaker, alice)
    rows = [(f"{texts[i % len(texts)]} {i}", "100.00", "debit") for i in range(TXNS)]
    for i in range(0, TXNS, 1000):  # asyncpg allows 32k bind parameters per statement
        await add_txns(sessionmaker, alice, acc, rows[i : i + 1000])
    async with unit_of_work(sessionmaker, alice.user_id) as uow:
        from finboard.services.jobs import JobService

        job = await JobService(uow, job_queue).submit("ai.embed_all")
    started = time.perf_counter()
    await job_queue.drain(("ai.embed_all",))
    elapsed = time.perf_counter() - started
    assert not job_queue.failures
    async with unit_of_work(sessionmaker, alice.user_id) as uow:
        assert await uow.embeddings.counts(embedding_key(settings.embed_model)) == (TXNS, TXNS)
        assert (await uow.jobs.get(job.id)) is not None
    # ru_maxrss is the whole test process (an upper bound for a worker): KB on Linux.
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (
        1024 * 1024 if sys.platform == "darwin" else 1024
    )
    print(f"\nembedded {TXNS} in {elapsed:.1f}s, peak RSS {peak_mb:.0f} MB")
    assert elapsed < 60
    assert peak_mb < 600
