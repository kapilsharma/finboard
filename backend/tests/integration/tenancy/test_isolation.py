"""User B must never see or touch user A's data through the API (ADR-0025, layer 1)."""

import httpx
import pytest

BOB = {"X-Test-User": "bob"}


@pytest.fixture
async def alices_data(client: httpx.AsyncClient) -> dict[str, str]:
    account = (
        await client.post("/api/v1/accounts", json={"name": "Alice ICICI", "type": "savings"})
    ).json()
    category = (
        await client.post("/api/v1/categories", json={"name": "Alice pets", "type": "expense"})
    ).json()
    job = (await client.post("/api/v1/jobs/ping")).json()
    return {"account": account["id"], "category": category["id"], "job": job["id"]}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/api/v1/accounts/{account}", None),
        ("PATCH", "/api/v1/accounts/{account}", {"name": "pwned"}),
        ("DELETE", "/api/v1/accounts/{account}", None),
        ("PATCH", "/api/v1/categories/{category}", {"name": "pwned"}),
        ("DELETE", "/api/v1/categories/{category}", None),
        ("GET", "/api/v1/jobs/{job}", None),
    ],
)
async def test_other_users_ids_are_404(
    client: httpx.AsyncClient,
    alices_data: dict[str, str],
    method: str,
    path: str,
    body: dict[str, str] | None,
) -> None:
    response = await client.request(method, path.format(**alices_data), json=body, headers=BOB)
    assert response.status_code == 404
    # …and Alice's data is unchanged.
    assert (await client.get(f"/api/v1/accounts/{alices_data['account']}")).json()[
        "name"
    ] == "Alice ICICI"


async def test_lists_only_show_own_rows(
    client: httpx.AsyncClient, alices_data: dict[str, str]
) -> None:
    assert (await client.get("/api/v1/accounts", headers=BOB)).json()["items"] == []
    assert (await client.get("/api/v1/jobs", headers=BOB)).json()["items"] == []
    bob_categories = (await client.get("/api/v1/categories", headers=BOB)).json()["items"]
    assert "Alice pets" not in [c["name"] for c in bob_categories]


async def test_names_are_unique_per_user_only(
    client: httpx.AsyncClient, alices_data: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/accounts", json={"name": "Alice ICICI", "type": "savings"}, headers=BOB
    )
    assert response.status_code == 201


async def test_cannot_parent_under_another_users_category(
    client: httpx.AsyncClient, alices_data: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/categories",
        json={"name": "Sneaky", "type": "expense", "parent_id": alices_data["category"]},
        headers=BOB,
    )
    assert response.status_code == 422
