"""A hung parser is killed by the hard time limit; the import fails and the worker recovers.

Needs Celery's prefork pool, which isn't available on Windows hosts (the dev worker there uses
`--pool=solo`, where time limits don't apply). CI runs this on Linux.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from finboard.auth import Principal
from finboard.core.config import Settings
from finboard.jobs.celery_app import celery_app
from finboard.jobs.queue import CeleryJobQueue
from finboard.main import create_app

from .conftest import HeaderAuthBackend
from .fake_parsers import marker_pdf
from .imports_helpers import API, statement, upload

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="hard time limits need the prefork pool (Linux, macOS)"
)

BACKEND_DIR = Path(__file__).resolve().parents[2]
# Generous enough for a cold worker's first task (imports, DB pool) to reach parse().
SOFT_LIMIT, HARD_LIMIT = 4, 7


@pytest.fixture
def worker() -> Iterator[subprocess.Popen[bytes]]:
    celery_app.control.purge()  # drop anything left in the test broker by earlier runs
    env = {
        **os.environ,
        "FINBOARD_PARSE_SOFT_TIME_LIMIT": str(SOFT_LIMIT),
        "FINBOARD_PARSE_TIME_LIMIT": str(HARD_LIMIT),
        "PYTHONPATH": os.pathsep.join(
            filter(None, [str(BACKEND_DIR), os.environ.get("PYTHONPATH")])
        ),
    }
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "celery",
            "-A",
            "finboard.jobs.celery_app:celery_app",
            "worker",
            "--pool=prefork",
            "--concurrency=1",
            "--queues=parse,default",
            "--loglevel=WARNING",
            "--without-gossip",
            "--without-mingle",
        ],
        cwd=BACKEND_DIR,
        env=env,
    )
    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
async def live_client(
    settings: Settings, alice: Principal, bob: Principal
) -> AsyncIterator[httpx.AsyncClient]:
    app: FastAPI = create_app(
        settings,
        auth_backend=HeaderAuthBackend({"alice": alice, "bob": bob}, default="alice"),
        job_queue=CeleryJobQueue(celery_app),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://127.0.0.1",
            headers={"X-Finboard-Client": "1"},
        ) as client,
    ):
        yield client


async def wait_for(
    client: httpx.AsyncClient, import_id: str, statuses: set[str], limit_s: float = 60
) -> dict[str, Any]:
    deadline = time.monotonic() + limit_s
    while True:
        body: dict[str, Any] = (await client.get(f"{API}/imports/{import_id}")).json()
        if body["status"] in statuses:
            return body
        if time.monotonic() > deadline:
            raise AssertionError(f"import stuck in {body['status']}")
        await asyncio.sleep(0.25)


async def test_hung_parser_is_killed_and_worker_recovers(
    worker: subprocess.Popen[bytes], live_client: httpx.AsyncClient
) -> None:
    hung = await upload(live_client, marker_pdf("HANG-FIXTURE"))
    started = time.monotonic()
    failed = await wait_for(live_client, hung["id"], {"failed", "parsed"})
    assert failed["status"] == "failed"
    assert failed["error"] == "Reading the statement took too long"
    assert failed["job"]["status"] == "failed"
    assert time.monotonic() - started >= HARD_LIMIT - 0.5  # the hard limit, not something else

    # The pool replaced the killed process: the next statement parses normally.
    data, expected = statement(seed=60, rows=5)
    ok = await upload(live_client, data)
    parsed = await wait_for(live_client, ok["id"], {"parsed", "failed"})
    assert parsed["status"] == "parsed", parsed
    assert parsed["counts"]["parsed"] == len(expected.transactions)
    assert worker.poll() is None
