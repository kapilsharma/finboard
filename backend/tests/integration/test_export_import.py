"""Export → delete-all → import gives an identical dataset; bad zips are refused (ARCHITECTURE
§10, §13, ROADMAP M5)."""

import hashlib
import io
import json
import zipfile
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.core.config import Settings
from finboard.db.uow import unit_of_work
from finboard.services.data import table_checksum
from finboard.services.demo import load_demo

from .categorisation_helpers import category_id
from .conftest import RecordingJobQueue
from .imports_helpers import API, blob_files, commit, parsed, statement


async def run_job(
    client: httpx.AsyncClient, queue: RecordingJobQueue, response: httpx.Response
) -> dict[str, Any]:
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]["id"]
    await queue.drain_all()
    job: dict[str, Any] = (await client.get(f"{API}/jobs/{job_id}")).json()
    return job


async def snapshot(sm: async_sessionmaker[AsyncSession], user: Principal) -> dict[str, str]:
    from finboard.services.data import DataService

    async with unit_of_work(sm, user.user_id) as uow:
        tables = await DataService(uow, RecordingJobQueue(), None).snapshot()  # type: ignore[arg-type]
    return {name: f"{len(rows)}:{table_checksum(rows)}" for name, rows in tables.items()}


async def export_zip(client: httpx.AsyncClient, queue: RecordingJobQueue) -> bytes:
    job = await run_job(client, queue, await client.post(f"{API}/data/export"))
    assert job["status"] == "succeeded", job
    response = await client.get(f"{API}/data/exports/{job['id']}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    return response.content


async def import_zip(
    client: httpx.AsyncClient, queue: RecordingJobQueue, data: bytes
) -> dict[str, Any]:
    response = await client.post(
        f"{API}/data/import", files={"file": ("export.zip", data, "application/zip")}
    )
    if response.status_code != 202:
        return {
            "status": "refused",
            "error": response.json()["detail"],
            "code": response.status_code,
        }
    return await run_job(client, queue, response)


@pytest.fixture
async def rich_data(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    """Demo data, a committed statement with its archived PDF, a transfer pair, settings."""
    async with unit_of_work(sessionmaker, alice.user_id) as uow:
        await load_demo(uow)
    body = await parsed(client, job_queue, statement(seed=5, rows=8)[0])
    assert (
        await commit(client, body["id"], create_account={"name": "Kotak", "type": "savings"})
    ).status_code == 200
    await job_queue.drain_all()  # transfer pairing after the commit
    await client.patch(f"{API}/settings", json={"theme": "dark"})
    await client.patch(
        f"{API}/parsers/test_options", json={"options": {"institution_label": "Kept"}}
    )
    rent = await category_id(client, "Rent")
    await client.put(
        f"{API}/budgets/{rent}", json={"effective_from": "2026-09", "monthly_limit": "33000.00"}
    )


async def test_export_delete_all_import_round_trip(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
    settings: Settings,
    rich_data: None,
) -> None:
    before = await snapshot(sessionmaker, alice)
    pdfs_before = {
        p.name: c
        for p, c in blob_files(settings.blob_dir / "users" / str(alice.user_id) / "imports").items()
    }
    assert pdfs_before, "the committed statement should be archived"
    exported = await export_zip(client, job_queue)
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert {n for n in archive.namelist() if n.startswith("pdfs/")} == {
            f"pdfs/{n}.pdf" for n in pdfs_before
        }
    assert manifest["counts"]["transactions"] == 84 + 8

    # Delete all: an empty Finboard with the defaults again, and no files.
    job = await run_job(
        client,
        job_queue,
        await client.post(f"{API}/data/delete-all", json={"confirm": "DELETE ALL"}),
    )
    assert job["status"] == "succeeded", job
    assert (await client.get(f"{API}/dashboard")).json() is None
    assert not (settings.blob_dir / "users" / str(alice.user_id)).exists()
    assert len((await client.get(f"{API}/categories")).json()["items"]) > 10  # defaults back

    job = await import_zip(client, job_queue, exported)
    assert job["status"] == "succeeded", job
    assert await snapshot(sessionmaker, alice) == before
    pdfs_after = {
        p.name: c
        for p, c in blob_files(settings.blob_dir / "users" / str(alice.user_id) / "imports").items()
    }
    assert pdfs_after == pdfs_before
    # Exporting again gives the same tables.
    with zipfile.ZipFile(io.BytesIO(await export_zip(client, job_queue))) as archive:
        assert json.loads(archive.read("manifest.json"))["checksums"] == manifest["checksums"]
    # The restored Finboard still recognises the statement it has seen.
    again = await parsed(client, job_queue, statement(seed=5, rows=8)[0])
    kotak = next(
        a for a in (await client.get(f"{API}/accounts")).json()["items"] if a["name"] == "Kotak"
    )
    reparsed = await client.post(
        f"{API}/imports/{again['id']}/reparse", json={"account_id": kotak["id"]}
    )
    assert reparsed.status_code == 202
    again = (await client.get(f"{API}/imports/{again['id']}")).json()
    assert again["counts"]["duplicate"] == 8
    assert (await client.get(f"{API}/dashboard", params={"month": "2026-09"})).json()["headline"][
        "income"
    ]["value"] == "142702.04"


async def test_import_needs_an_empty_finboard(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, rich_data: None
) -> None:
    exported = await export_zip(client, job_queue)
    result = await import_zip(client, job_queue, exported)
    assert result["status"] == "refused" and result["code"] == 409


async def test_delete_all_needs_the_typed_confirmation(client: httpx.AsyncClient) -> None:
    for confirm in ("delete all", "DELETE", ""):
        response = await client.post(f"{API}/data/delete-all", json={"confirm": confirm})
        assert response.status_code == 422


async def test_csv_export(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> None:
    from .categorisation_helpers import account, add_txns

    acc = await account(sessionmaker, alice)
    await add_txns(
        sessionmaker,
        alice,
        acc,
        [('=HYPERLINK("http://x")', "10.00", "debit"), ("TEA, HOT", "5.50", "debit")],
    )
    response = await client.get(f"{API}/data/transactions.csv")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/csv")
    lines = response.text.splitlines()
    assert lines[0] == "date,description,account,category,type,direction,amount,needs_review,notes"
    assert any(line.startswith("2026-09-10,\"'=HYPERLINK(") for line in lines)  # not a formula
    assert any('"TEA, HOT"' in line and ",5.50," in line for line in lines)


# ---------------------------------------------------------------- malicious and broken zips


def make_zip(members: dict[str, bytes], *, symlink: str | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = 0o120777 << 16
            archive.writestr(info, "/etc/passwd")
    return buffer.getvalue()


@pytest.fixture
async def valid_members(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> dict[str, bytes]:
    async with unit_of_work(sessionmaker, alice.user_id) as uow:
        await load_demo(uow)
    exported = await export_zip(client, job_queue)
    await run_job(
        client,
        job_queue,
        await client.post(f"{API}/data/delete-all", json={"confirm": "DELETE ALL"}),
    )
    with zipfile.ZipFile(io.BytesIO(exported)) as archive:
        return {n: archive.read(n) for n in archive.namelist()}


def with_manifest(members: dict[str, bytes], **changes: Any) -> dict[str, bytes]:
    manifest = json.loads(members["manifest.json"])
    manifest.update(changes)
    return {**members, "manifest.json": json.dumps(manifest).encode()}


async def assert_rejected(
    client: httpx.AsyncClient, queue: RecordingJobQueue, data: bytes, message: str
) -> None:
    job = await import_zip(client, queue, data)
    assert job["status"] == "failed", job
    assert message in job["error"], job["error"]
    # Nothing was written.
    assert (await client.get(f"{API}/dashboard")).json() is None


async def test_rejects_path_traversal(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, valid_members: dict[str, bytes]
) -> None:
    await assert_rejected(
        client,
        job_queue,
        make_zip({**valid_members, "../../etc/cron.d/x": b"x"}),
        "Unexpected file",
    )
    await assert_rejected(
        client, job_queue, make_zip({**valid_members, "pdfs/../../x.pdf": b"x"}), "Unexpected file"
    )
    await assert_rejected(
        client, job_queue, make_zip({**valid_members, "/abs.pdf": b"x"}), "Unexpected file"
    )


async def test_rejects_extra_members_and_symlinks(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, valid_members: dict[str, bytes]
) -> None:
    await assert_rejected(
        client, job_queue, make_zip({**valid_members, "notes.txt": b"hi"}), "Unexpected file"
    )
    await assert_rejected(
        client,
        job_queue,
        make_zip(valid_members, symlink="pdfs/01900000-0000-7000-8000-000000000000.pdf"),
        "Unexpected entry",
    )
    stray = {**valid_members, "pdfs/01900000-0000-7000-8000-000000000000.pdf": b"%PDF-1.4"}
    await assert_rejected(client, job_queue, make_zip(stray), "checksum")


async def test_rejects_newer_version(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, valid_members: dict[str, bytes]
) -> None:
    await assert_rejected(
        client, job_queue, make_zip(with_manifest(valid_members, version=2)), "newer Finboard"
    )
    await assert_rejected(
        client,
        job_queue,
        make_zip(with_manifest(valid_members, format="other")),
        "isn't a Finboard export",
    )


async def test_rejects_tampered_data(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, valid_members: dict[str, bytes]
) -> None:
    data = json.loads(valid_members["data.json"])
    data["transactions"][0]["amount"] = "999999.00"
    await assert_rejected(
        client,
        job_queue,
        make_zip({**valid_members, "data.json": json.dumps(data).encode()}),
        "checksum",
    )
    data = json.loads(valid_members["data.json"])
    data["transactions"][0]["evil"] = "x"
    await assert_rejected(
        client,
        job_queue,
        make_zip({**valid_members, "data.json": json.dumps(data).encode()}),
        "columns",
    )
    data = json.loads(valid_members["data.json"])
    data["transactions"][0]["amount"] = 12.5  # floats are never money
    await assert_rejected(
        client,
        job_queue,
        make_zip({**valid_members, "data.json": json.dumps(data).encode()}),
        "not valid",
    )
    missing = {k: v for k, v in valid_members.items() if k != "data.json"}
    await assert_rejected(client, job_queue, make_zip(missing), "missing")
    await assert_rejected(client, job_queue, b"not a zip at all", "isn't a zip")


async def test_rejects_zip_bombs(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, valid_members: dict[str, bytes]
) -> None:
    bomb = {**valid_members, "data.json": b"[" + b" " * (64 << 20) + b"]"}  # compresses ~1000:1
    await assert_rejected(client, job_queue, make_zip(bomb), "compressed suspiciously well")


async def test_export_of_another_user_is_not_downloadable(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    job = await run_job(client, job_queue, await client.post(f"{API}/data/export"))
    response = await client.get(f"{API}/data/exports/{job['id']}", headers={"X-Test-User": "bob"})
    assert response.status_code == 404


def test_checksum_is_order_and_type_stable() -> None:
    rows = [{"a": 1, "b": "x"}]
    assert table_checksum(rows) == table_checksum([{"b": "x", "a": 1}])
    assert table_checksum(rows) == hashlib.sha256(b'[{"a":1,"b":"x"}]').hexdigest()
