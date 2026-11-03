"""Single-port mode: FastAPI serves the built SPA next to the API."""

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from finboard.auth import LocalSingleUserBackend, Principal
from finboard.core.config import Settings
from finboard.main import create_app


@pytest.fixture
async def spa_client(
    settings: Settings, alice: Principal, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    (tmp_path / "index.html").write_text("<title>Finboard</title>", encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    app = create_app(
        settings.model_copy(update={"static_dir": tmp_path}),
        auth_backend=LocalSingleUserBackend(alice),
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            yield client


async def test_serves_index_and_assets(spa_client: httpx.AsyncClient) -> None:
    assert "Finboard" in (await spa_client.get("/")).text
    assert (await spa_client.get("/assets/app.js")).text == "console.log(1)"


async def test_client_routes_fall_back_to_index(spa_client: httpx.AsyncClient) -> None:
    response = await spa_client.get("/settings/accounts")
    assert response.status_code == 200
    assert "Finboard" in response.text


async def test_unknown_api_paths_stay_404_json(spa_client: httpx.AsyncClient) -> None:
    response = await spa_client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"


async def test_api_still_wins_over_static(spa_client: httpx.AsyncClient) -> None:
    assert (await spa_client.get("/api/v1/me")).json()["username"] == "alice"
