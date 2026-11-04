"""Retried POSTs with the same Idempotency-Key run once (ARCHITECTURE §4)."""

import httpx

from .conftest import RecordingJobQueue
from .imports_helpers import API, create_account, parsed, statement, upload


async def test_retried_upload_creates_one_import(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    data, _ = statement(seed=40, rows=4)
    key = {"Idempotency-Key": "upload-1"}
    first = await upload(client, data, headers=key)
    retry = await client.post(
        f"{API}/imports", files={"file": ("statement.pdf", data, "application/pdf")}, headers=key
    )
    assert retry.status_code == 202
    assert retry.headers["Idempotent-Replayed"] == "true"
    assert retry.json()["id"] == first["id"]
    assert len((await client.get(f"{API}/imports")).json()["items"]) == 1
    assert len(job_queue.enqueued) == 1

    other = await upload(client, data, headers={"Idempotency-Key": "upload-2"})
    assert other["id"] != first["id"]


async def test_keys_are_per_user(client: httpx.AsyncClient, job_queue: RecordingJobQueue) -> None:
    data, _ = statement(seed=41, rows=2)
    mine = await upload(client, data, headers={"Idempotency-Key": "same"})
    theirs = await upload(client, data, headers={"Idempotency-Key": "same", "X-Test-User": "bob"})
    assert mine["id"] != theirs["id"]


async def test_retried_commit_replays_the_result(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    data, expected = statement(seed=44, rows=6)
    await create_account(client, expected.account_hint)
    body = await parsed(client, job_queue, data)
    key = {"Idempotency-Key": "commit-1"}
    first = await client.post(f"{API}/imports/{body['id']}/commit", json={}, headers=key)
    retry = await client.post(f"{API}/imports/{body['id']}/commit", json={}, headers=key)
    assert first.status_code == retry.status_code == 200
    assert retry.json() == first.json()
    assert retry.json()["result"]["inserted"] == 6
    # Without the key a second commit is a conflict, not a silent no-op.
    plain = await client.post(f"{API}/imports/{body['id']}/commit", json={})
    assert plain.status_code == 409


async def test_failed_request_is_not_cached(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    body = await parsed(client, job_queue, statement(seed=43, rows=2)[0])
    key = {"Idempotency-Key": "commit-2"}
    first = await client.post(f"{API}/imports/{body['id']}/commit", json={}, headers=key)
    assert first.status_code == 422  # no account yet
    retry = await client.post(
        f"{API}/imports/{body['id']}/commit",
        json={"create_account": {"name": "Card", "type": "savings"}},
        headers=key,
    )
    assert retry.status_code == 200
