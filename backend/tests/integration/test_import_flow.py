"""The import pipeline end to end (ARCHITECTURE §7, ROADMAP M2)."""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from finboard.auth import Principal
from finboard.core.config import Settings
from finboard.jobs.queue import CeleryJobQueue

from .conftest import RecordingJobQueue
from .fake_parsers import marker_pdf
from .imports_helpers import (
    API,
    PASSWORD,
    blob_files,
    commit,
    create_account,
    get,
    parsed,
    statement,
    upload,
)


async def txn_count(engine: AsyncEngine, user: Principal) -> int:
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user.user_id)}
        )
        return int((await conn.execute(text("SELECT count(*) FROM txn"))).scalar_one())


# ---------------------------------------------------------------- encrypted statements


async def test_encrypted_needs_password_then_wrong_then_right(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    data, expected = statement(seed=2, rows=15, password=PASSWORD)
    created = await upload(client, data)
    assert created["status"] == "queued"
    assert created["job"]["status"] == "queued"

    await job_queue.drain()
    locked = await get(client, created["id"])
    assert locked["status"] == "needs_password"
    assert locked["encrypted"] is True
    assert locked["error"] is None

    response = await client.post(
        f"{API}/imports/{created['id']}/unlock", json={"password": "not-it"}
    )
    assert response.status_code == 202
    assert response.json()["status"] == "queued"
    await job_queue.drain()
    wrong = await get(client, created["id"])
    assert wrong["status"] == "needs_password"
    assert "didn't open" in wrong["error"]

    await client.post(f"{API}/imports/{created['id']}/unlock", json={"password": PASSWORD})
    await job_queue.drain()
    preview = await get(client, created["id"])
    assert preview["status"] == "parsed"
    assert preview["parser"]["id"] == "generic_table"
    assert preview["counts"]["parsed"] == len(expected.transactions) == len(preview["rows"])
    assert preview["reconciliation"]["status"] == "ok"
    assert preview["rows"][0]["amount"] == f"{expected.transactions[0].amount:.2f}"
    # No account with this number yet: Finboard suggests one.
    assert preview["account"] is None
    assert preview["account_suggestion"]["create"]["masked_number"] == expected.account_hint

    draft = preview["account_suggestion"]["create"]
    done = await commit(client, created["id"], create_account=draft)
    assert done.status_code == 200, done.text
    assert done.json()["result"] == {
        "inserted": len(expected.transactions),
        "skipped": 0,
        "excluded": 0,
    }
    assert done.json()["account"]["masked_number"] == expected.account_hint


async def test_unlock_only_when_waiting_for_password(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    body = await parsed(client, job_queue, statement()[0])
    response = await client.post(f"{API}/imports/{body['id']}/unlock", json={"password": "x"})
    assert response.status_code == 409


class _Collect(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))


async def test_password_never_persisted(
    app: FastAPI,
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    app_engine: AsyncEngine,
    alice: Principal,
    settings: Settings,
) -> None:
    root = logging.getLogger()
    collector = _Collect()
    collector.setFormatter(root.handlers[0].formatter)
    root.addHandler(collector)
    old_level = root.level
    root.setLevel(logging.DEBUG)
    try:
        data, _ = statement(seed=4, rows=8, password=PASSWORD)
        created = await upload(client, data)
        await job_queue.drain()
        await client.post(f"{API}/imports/{created['id']}/unlock", json={"password": "wrong"})
        await job_queue.drain()
        await client.post(f"{API}/imports/{created['id']}/unlock", json={"password": PASSWORD})
        await job_queue.drain()
        assert (await get(client, created["id"]))["status"] == "parsed"
    finally:
        root.removeHandler(collector)
        root.setLevel(old_level)

    # Logs (API and worker, every level).
    assert collector.lines, "expected some log output"
    assert not [line for line in collector.lines if PASSWORD in line]

    # Broker messages: only ids and an opaque reference.
    assert PASSWORD not in repr(job_queue.enqueued)
    refs = [e["secret_ref"] for e in job_queue.enqueued if e["secret_ref"]]
    assert len(refs) == 2

    # Postgres: every table the user can see, job params included.
    async with app_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.user_id', :u, true)"), {"u": str(alice.user_id)}
        )
        tables = (
            await conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'"))
        ).scalars()
        dumped = []
        for table in tables:
            rows = await conn.execute(text(f'SELECT row_to_json(t)::text FROM "{table}" t'))
            dumped.extend(rows.scalars())
    assert dumped and not [row for row in dumped if PASSWORD in row]

    # Blobs keep the original encrypted bytes, which never contain the password.
    blobs = blob_files(settings.blob_dir)
    assert blobs and not [p for p, data in blobs.items() if PASSWORD.encode() in data]

    # Redis: the single-use secrets are gone.
    redis = app.state.redis
    assert await redis.keys("secret:*") == []
    for ref in refs:
        assert await redis.get(f"secret:{ref}") is None


async def test_celery_message_carries_only_ids() -> None:
    sent: list[dict[str, object]] = []

    class FakeCelery:
        def send_task(self, name: str, kwargs: dict[str, object], task_id: str) -> None:
            sent.append({"name": name, "kwargs": kwargs, "task_id": task_id})

    import uuid

    job_id, user_id = uuid.uuid4(), uuid.uuid4()
    await CeleryJobQueue(FakeCelery()).enqueue(  # type: ignore[arg-type]
        kind="imports.process", job_id=job_id, user_id=user_id, secret_ref="ab" * 16
    )
    assert sent == [
        {
            "name": "imports.process",
            "kwargs": {"job_id": str(job_id), "user_id": str(user_id), "secret_ref": "ab" * 16},
            "task_id": str(job_id),
        }
    ]


async def test_expired_password_asks_again(
    app: FastAPI, client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    data, _ = statement(seed=5, rows=5, password=PASSWORD)
    created = await upload(client, data)
    await job_queue.drain()
    await client.post(f"{API}/imports/{created['id']}/unlock", json={"password": PASSWORD})
    await app.state.redis.delete(*(await app.state.redis.keys("secret:*")))  # TTL ran out
    await job_queue.drain()
    body = await get(client, created["id"])
    assert body["status"] == "needs_password"
    assert "expired" in body["error"]


# ---------------------------------------------------------------- dedupe and concurrency


async def test_idempotent(client: httpx.AsyncClient, job_queue: RecordingJobQueue) -> None:
    data, expected = statement(seed=7, rows=20)
    account = await create_account(client, expected.account_hint)
    first = await parsed(client, job_queue, data)
    assert first["account"]["id"] == account["id"]  # matched on the last 4 digits
    assert (await commit(client, first["id"])).json()["result"]["inserted"] == 20

    again = await parsed(client, job_queue, data)
    assert again["file_already_imported"]["import_id"] == first["id"]
    assert again["counts"]["duplicate"] == 20 and again["counts"]["new"] == 0
    assert all(r["duplicate"] and not r["include"] for r in again["rows"])
    result = (await commit(client, again["id"])).json()["result"]
    assert result == {"inserted": 0, "skipped": 20, "excluded": 0}


async def test_concurrent_commit(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    app_engine: AsyncEngine,
    alice: Principal,
) -> None:
    data, expected = statement(seed=8, rows=25)
    await create_account(client, expected.account_hint)
    a = await parsed(client, job_queue, data)
    b = await parsed(client, job_queue, data)
    # Both previews were built before either commit, so neither knows about the other.
    assert a["counts"]["new"] == b["counts"]["new"] == 25

    ra, rb = await asyncio.gather(commit(client, a["id"]), commit(client, b["id"]))
    assert ra.status_code == rb.status_code == 200
    results = [ra.json()["result"], rb.json()["result"]]
    assert sorted(r["inserted"] for r in results) == [0, 25]
    assert sorted(r["skipped"] for r in results) == [0, 25]
    assert await txn_count(app_engine, alice) == 25


async def test_double_commit_is_refused(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    data, expected = statement(seed=10, rows=5)
    await create_account(client, expected.account_hint)
    body = await parsed(client, job_queue, data)
    first, second = await asyncio.gather(commit(client, body["id"]), commit(client, body["id"]))
    assert sorted([first.status_code, second.status_code]) == [200, 409]


async def test_rollback_overlap(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    app_engine: AsyncEngine,
    alice: Principal,
) -> None:
    data, expected = statement(seed=11, rows=10)
    await create_account(client, expected.account_hint)
    a = await parsed(client, job_queue, data)
    assert (await commit(client, a["id"])).json()["result"]["inserted"] == 10

    # B sees the same rows (all duplicates); the user excludes three of them.
    b = await parsed(client, job_queue, data)
    for seq in (0, 1, 2):
        response = await client.patch(
            f"{API}/imports/{b['id']}/rows/{seq}", json={"include": False}
        )
        assert response.status_code == 200
    assert (await commit(client, b["id"])).json()["result"]["skipped"] == 10

    rolled = await client.post(f"{API}/imports/{a['id']}/rollback")
    assert rolled.status_code == 200
    assert rolled.json()["status"] == "rolled_back"
    # Rows B also saw stay (now owned by B); B also "saw" the excluded duplicates, so all stay.
    assert await txn_count(app_engine, alice) == 10
    async with app_engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.user_id', :u, true)"), {"u": str(alice.user_id)}
        )
        owners = (await conn.execute(text("SELECT DISTINCT import_id FROM txn"))).scalars().all()
    assert [str(o) for o in owners] == [b["id"]]

    # Rolling back B now removes everything, and A can't be rolled back twice.
    assert (await client.post(f"{API}/imports/{b['id']}/rollback")).status_code == 200
    assert await txn_count(app_engine, alice) == 0
    assert (await client.post(f"{API}/imports/{a['id']}/rollback")).status_code == 409


async def test_rollback_keeps_only_rows_the_later_import_saw(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    app_engine: AsyncEngine,
    alice: Principal,
) -> None:
    """A commits 10 rows; B is the same statement but committed with 4 rows excluded while
    they were still *new* (B parsed before A committed): B never saw those 4."""
    data, expected = statement(seed=22, rows=10)
    await create_account(client, expected.account_hint)
    a = await parsed(client, job_queue, data)
    b = await parsed(client, job_queue, data)
    for seq in range(4):
        await client.patch(f"{API}/imports/{b['id']}/rows/{seq}", json={"include": False})
    assert (await commit(client, a["id"])).json()["result"]["inserted"] == 10
    result = (await commit(client, b["id"])).json()["result"]
    assert result == {"inserted": 0, "skipped": 6, "excluded": 4}

    await client.post(f"{API}/imports/{a['id']}/rollback")
    assert await txn_count(app_engine, alice) == 6


# ---------------------------------------------------------------- reconciliation


async def test_reconciliation_mismatch_blocks_commit_until_overridden(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    await create_account(client, "4242")
    body = await parsed(client, job_queue, marker_pdf("MISMATCH-FIXTURE"))
    recon = body["reconciliation"]
    assert recon["status"] == "mismatch"
    assert recon["expected_closing"] == "890.00" and recon["diff"] == "10.00"

    blocked = await commit(client, body["id"])
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "reconciliation_mismatch"

    done = await commit(client, body["id"], override_reconciliation=True)
    assert done.status_code == 200
    assert done.json()["reconciliation"]["overridden"] is True
    assert done.json()["result"]["inserted"] == 2


async def test_credit_card_statement_reconciles_as_liability(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    data, expected = statement(seed=6, rows=18)  # seed % 3 == 0 → credit card
    assert expected.balance_kind == "liability"
    body = await parsed(client, job_queue, data)
    suggestion = body["account_suggestion"]["create"]
    assert suggestion["type"] == "credit_card"
    assert body["reconciliation"]["status"] == "ok"
    assert body["reconciliation"]["balance_kind"] == "liability"
    done = await commit(client, body["id"], create_account=suggestion)
    assert done.json()["reconciliation"]["status"] == "ok"


# ---------------------------------------------------------------- preview edits, discard, limits


async def test_preview_row_edits_and_account_reparse(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    data, _ = statement(seed=13, rows=6)
    body = await parsed(client, job_queue, data)
    assert body["account"] is None

    response = await client.patch(f"{API}/imports/{body['id']}/rows/2", json={"include": False})
    assert response.json()["counts"]["excluded"] == 1
    bad = await client.patch(f"{API}/imports/{body['id']}/rows/99", json={"include": False})
    assert bad.status_code == 404

    account = await create_account(client, None, name="Picked by hand")
    response = await client.post(
        f"{API}/imports/{body['id']}/reparse", json={"account_id": account["id"]}
    )
    assert response.status_code == 202
    assert response.json()["status"] == "parsed"  # account-only change: no new parse job
    assert response.json()["account"]["id"] == account["id"]
    assert response.json()["counts"]["excluded"] == 1

    reparse = await client.post(
        f"{API}/imports/{body['id']}/reparse", json={"parser_id": "test_mismatch"}
    )
    assert reparse.json()["status"] == "queued"
    unknown = await client.post(f"{API}/imports/{body['id']}/reparse", json={"parser_id": "nope"})
    assert unknown.status_code == 409  # already queued again


async def test_commit_needs_an_account(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    body = await parsed(client, job_queue, statement(seed=14, rows=3)[0])
    response = await commit(client, body["id"])
    assert response.status_code == 422
    assert "account" in response.json()["detail"]


async def test_discard_removes_rows_and_file(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, settings: Settings
) -> None:
    body = await parsed(client, job_queue, statement(seed=15, rows=4)[0])
    before = set(blob_files(settings.blob_dir))
    assert (await client.delete(f"{API}/imports/{body['id']}")).status_code == 204
    after = set(blob_files(settings.blob_dir))
    assert len(before - after) == 1
    gone = await get(client, body["id"])
    assert gone["status"] == "discarded" and gone["rows"] is None
    assert (await commit(client, body["id"])).status_code == 409


async def test_committed_import_cannot_be_discarded(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    data, expected = statement(seed=16, rows=3)
    await create_account(client, expected.account_hint)
    body = await parsed(client, job_queue, data)
    await commit(client, body["id"])
    assert (await client.delete(f"{API}/imports/{body['id']}")).status_code == 409


async def test_account_with_transactions_cannot_be_deleted(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    data, expected = statement(seed=17, rows=3)
    account = await create_account(client, expected.account_hint)
    body = await parsed(client, job_queue, data)
    await commit(client, body["id"])
    response = await client.delete(f"{API}/accounts/{account['id']}")
    assert response.status_code == 409
    assert "Archive" in response.json()["detail"]


async def test_upload_limits(
    client: httpx.AsyncClient, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    not_pdf = await client.post(
        f"{API}/imports", files={"file": ("x.pdf", b"hello", "application/pdf")}
    )
    assert not_pdf.status_code == 422
    missing = await client.post(f"{API}/imports", files={"other": ("x.pdf", b"%PDF-1.4")})
    assert missing.status_code == 422

    monkeypatch.setattr(settings, "max_upload_bytes", 2000)
    data, _ = statement(seed=18, rows=40)
    too_big = await client.post(
        f"{API}/imports", files={"file": ("big.pdf", data, "application/pdf")}
    )
    assert too_big.status_code == 413
    assert too_big.json()["code"] == "payload_too_large"


async def test_page_limit(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "max_pages", 1)
    data, _ = statement(seed=19, rows=80)  # two pages
    created = await upload(client, data)
    await job_queue.drain()
    body = await get(client, created["id"])
    assert body["status"] == "failed"
    assert "more than 1 pages" in body["error"]
    assert body["job"]["status"] == "failed"


async def test_soft_time_limit_fails_the_import(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    created = await upload(client, marker_pdf("SOFT-TIMEOUT"))
    await job_queue.drain()
    body = await get(client, created["id"])
    assert body["status"] == "failed"
    assert body["error"] == "Reading the statement took too long"
    assert body["job"]["error"] == "Reading the statement took too long"


async def test_unrecognised_file_fails_with_candidates(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    created = await upload(client, marker_pdf("nothing anyone recognises"))
    await job_queue.drain()
    body = await get(client, created["id"])
    assert body["status"] == "failed"
    assert "No parser recognised" in body["error"]
    assert {c["id"] for c in body["candidates"]} >= {"generic_table"}


async def test_per_user_parse_cap_queues_extra_uploads(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    ids = [(await upload(client, statement(seed=20 + i, rows=3)[0]))["id"] for i in range(3)]
    statuses = [(await get(client, i))["status"] for i in ids]
    assert statuses == ["queued", "queued", "uploaded"]  # cap = 2 per user
    await job_queue.drain()  # finishing one frees a slot, which starts the waiting upload
    assert [(await get(client, i))["status"] for i in ids] == ["parsed"] * 3


async def test_import_history_and_parsers(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    for seed in (30, 31, 32):
        await upload(client, statement(seed=seed, rows=2)[0])
    await job_queue.drain()
    page = (await client.get(f"{API}/imports", params={"limit": 2})).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    assert page["items"][0]["rows"] is None  # history has no rows
    rest = (
        await client.get(f"{API}/imports", params={"limit": 2, "cursor": page["next_cursor"]})
    ).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None
    only_parsed = (await client.get(f"{API}/imports", params={"status": "parsed"})).json()
    assert len(only_parsed["items"]) == 3

    parsers = (await client.get(f"{API}/parsers")).json()
    by_id = {p["id"]: p for p in parsers["items"]}
    assert by_id["generic_table"]["fallback"] is True
    assert parsers["failures"] == []
