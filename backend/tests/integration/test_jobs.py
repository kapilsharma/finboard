import asyncio
import uuid

import httpx
import pytest
from fastapi import FastAPI

from finboard.jobs import tasks

from .conftest import RecordingJobQueue


async def test_ping_job_round_trip(client: httpx.AsyncClient, job_queue: RecordingJobQueue) -> None:
    response = await client.post("/api/v1/jobs/ping")
    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued"
    [enqueued] = job_queue.enqueued
    assert enqueued["kind"] == "maintenance.ping"
    assert str(enqueued["job_id"]) == job["id"]

    # Run the real Celery task body, as a worker would (its own thread + event loop).
    await asyncio.to_thread(tasks.ping.run, job["id"], str(enqueued["user_id"]))

    done = (await client.get(f"/api/v1/jobs/{job['id']}")).json()
    assert done["status"] == "succeeded"
    assert done["progress"] == 100
    assert done["result"]["pong"] is True
    assert done["started_at"] is not None
    assert done["finished_at"] is not None


async def test_redelivered_job_runs_once(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    job = (await client.post("/api/v1/jobs/ping")).json()
    user_id = str(job_queue.enqueued[0]["user_id"])
    await asyncio.to_thread(tasks.ping.run, job["id"], user_id)
    finished = (await client.get(f"/api/v1/jobs/{job['id']}")).json()["finished_at"]

    await asyncio.to_thread(tasks.ping.run, job["id"], user_id)  # e.g. acks_late redelivery
    assert (await client.get(f"/api/v1/jobs/{job['id']}")).json()["finished_at"] == finished


async def test_jobs_list(client: httpx.AsyncClient) -> None:
    for _ in range(3):
        await client.post("/api/v1/jobs/ping")
    items = (await client.get("/api/v1/jobs")).json()["items"]
    assert len(items) == 3
    assert items[0]["created_at"] >= items[-1]["created_at"]


class BrokenQueue:
    async def enqueue(self, *, kind: str, job_id: uuid.UUID, user_id: uuid.UUID) -> None:
        raise ConnectionError("redis down")


async def test_queue_outage_returns_503_and_marks_job_failed(
    app: FastAPI, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app.state, "job_queue", BrokenQueue())
    response = await client.post("/api/v1/jobs/ping")
    assert response.status_code == 503
    assert response.json()["code"] == "service_unavailable"
    [job] = (await client.get("/api/v1/jobs")).json()["items"]
    assert job["status"] == "failed"
