import httpx

from finboard import __version__


async def test_live(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {}}


async def test_ready_checks_database_and_redis(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "redis": "ok"}}


async def test_meta(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/meta")
    assert response.json() == {"version": __version__, "api_version": "v1", "mode": "local"}


async def test_me_returns_the_authenticated_user(client: httpx.AsyncClient) -> None:
    alice = (await client.get("/api/v1/me")).json()
    bob = (await client.get("/api/v1/me", headers={"X-Test-User": "bob"})).json()
    assert alice["username"] == "alice"
    assert bob["username"] == "bob"
    assert alice["id"] != bob["id"]


async def test_unknown_api_path_is_problem_json(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/v1/nope")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
