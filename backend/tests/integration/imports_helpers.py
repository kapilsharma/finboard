"""Helpers shared by the import tests: synthetic statements and API shortcuts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from finboard.parsers.builtin.generic_table.fixtures import GenericTableFixtures
from finboard.parsers.sdk import ParsedStatement

from .conftest import RecordingJobQueue

API = "/api/v1"
PASSWORD = "Canary-Pw-7f3e91"  # distinctive, so it can be searched for everywhere


def statement(
    seed: int = 1, rows: int = 12, *, password: str | None = None
) -> tuple[bytes, ParsedStatement]:
    """A synthetic generic-table PDF. seed % 3 == 0 gives a credit-card (liability) statement."""
    return GenericTableFixtures().build(seed, rows, encrypted_with=password)


async def upload(
    client: httpx.AsyncClient,
    data: bytes,
    *,
    name: str = "statement.pdf",
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = await client.post(
        f"{API}/imports", files={"file": (name, data, "application/pdf")}, headers=headers
    )
    assert response.status_code == 202, response.text
    body: dict[str, Any] = response.json()
    return body


async def get(client: httpx.AsyncClient, import_id: str, **kw: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/imports/{import_id}", **kw)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def parsed(
    client: httpx.AsyncClient, queue: RecordingJobQueue, data: bytes, **kw: Any
) -> dict[str, Any]:
    """Upload, run the worker, return the parsed import."""
    created = await upload(client, data, **kw)
    await queue.drain()
    body = await get(client, created["id"], headers=kw.get("headers"))
    assert body["status"] == "parsed", body
    return body


async def create_account(
    client: httpx.AsyncClient, hint: str | None, *, type: str = "savings", name: str = "Main"
) -> dict[str, Any]:
    response = await client.post(
        f"{API}/accounts", json={"name": name, "type": type, "masked_number": hint}
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def commit(client: httpx.AsyncClient, import_id: str, **body: Any) -> httpx.Response:
    return await client.post(f"{API}/imports/{import_id}/commit", json=body)


def blob_files(root: Path) -> dict[Path, bytes]:
    """Every stored blob and its bytes (sync on purpose: tiny test directories)."""
    return {p: p.read_bytes() for p in Path(root).rglob("*") if p.is_file()}
