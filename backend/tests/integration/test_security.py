"""Local-mode request guards (ADR-0015)."""

import httpx
import pytest

ACCOUNT = {"name": "Savings", "type": "savings"}


@pytest.mark.parametrize("host", ["evil.com", "evil.com:8765", "127.0.0.1.nip.io", "10.0.0.5"])
async def test_foreign_host_is_rejected(client: httpx.AsyncClient, host: str) -> None:
    response = await client.get("/api/v1/me", headers={"Host": host})
    assert response.status_code == 421
    assert response.json()["code"] == "host_not_allowed"


@pytest.mark.parametrize("host", ["127.0.0.1:8765", "localhost:5173", "[::1]:8765", "LOCALHOST"])
async def test_loopback_hosts_are_allowed(client: httpx.AsyncClient, host: str) -> None:
    response = await client.get("/api/v1/me", headers={"Host": host})
    assert response.status_code == 200


async def test_mutation_without_client_header_is_rejected(client: httpx.AsyncClient) -> None:
    del client.headers["X-Finboard-Client"]
    response = await client.post("/api/v1/accounts", json=ACCOUNT)
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_check_failed"


async def test_cross_origin_mutation_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/accounts", json=ACCOUNT, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


async def test_same_origin_mutation_is_allowed(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/accounts",
        json=ACCOUNT,
        headers={"Origin": "http://localhost:5173", "Host": "localhost:5173"},
    )
    assert response.status_code == 201


async def test_reads_do_not_need_the_client_header(client: httpx.AsyncClient) -> None:
    del client.headers["X-Finboard-Client"]
    assert (await client.get("/api/v1/accounts")).status_code == 200


async def test_request_id_is_echoed_or_generated(client: httpx.AsyncClient) -> None:
    echoed = await client.get("/api/v1/health/live", headers={"X-Request-ID": "abcdef12-3456"})
    assert echoed.headers["X-Request-ID"] == "abcdef12-3456"
    generated = await client.get("/api/v1/health/live", headers={"X-Request-ID": "<script>"})
    assert len(generated.headers["X-Request-ID"]) == 32
