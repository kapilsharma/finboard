import httpx

from finboard.seed.categories import DEFAULT_CATEGORIES

URL = "/api/v1/categories"


async def _all(client: httpx.AsyncClient) -> list[dict[str, object]]:
    items: list[dict[str, object]] = (await client.get(URL)).json()["items"]
    return items


async def _by_name(client: httpx.AsyncClient, name: str) -> dict[str, object]:
    return next(c for c in await _all(client) if c["name"] == name)


async def test_new_users_get_the_default_categories(client: httpx.AsyncClient) -> None:
    categories = await _all(client)
    assert [c["name"] for c in categories] == [s.name for s in DEFAULT_CATEGORIES]
    system = {c["system_key"] for c in categories if c["is_system"]}
    assert system == {
        "card_payment",
        "own_transfer",
        "account_movement",
        "uncategorized",
        "uncategorized_income",
    }
    assert (await _by_name(client, "Insurance"))["type"] == "expense"  # owner decision OQ-26


async def test_create_child_category(client: httpx.AsyncClient) -> None:
    parent = await _by_name(client, "Investments")
    response = await client.post(
        URL, json={"name": "Flexi cap fund", "type": "investment", "parent_id": parent["id"]}
    )
    assert response.status_code == 201
    assert response.json()["parent_id"] == parent["id"]


async def test_only_two_levels(client: httpx.AsyncClient) -> None:
    parent = await _by_name(client, "Shopping")
    child = (
        await client.post(URL, json={"name": "Books", "type": "expense", "parent_id": parent["id"]})
    ).json()
    response = await client.post(
        URL, json={"name": "Novels", "type": "expense", "parent_id": child["id"]}
    )
    assert response.status_code == 422


async def test_same_name_allowed_under_different_parents(client: httpx.AsyncClient) -> None:
    shopping = await _by_name(client, "Shopping")
    health = await _by_name(client, "Health")
    for parent in (shopping, health):
        response = await client.post(
            URL, json={"name": "Online", "type": "expense", "parent_id": parent["id"]}
        )
        assert response.status_code == 201
    duplicate = await client.post(
        URL, json={"name": "online", "type": "expense", "parent_id": health["id"]}
    )
    assert duplicate.status_code == 409


async def test_top_level_names_are_unique(client: httpx.AsyncClient) -> None:
    response = await client.post(URL, json={"name": "groceries", "type": "expense"})
    assert response.status_code == 409


async def test_system_category_can_be_renamed_but_not_deleted_or_retyped(
    client: httpx.AsyncClient,
) -> None:
    card = await _by_name(client, "Card payment")
    renamed = await client.patch(f"{URL}/{card['id']}", json={"name": "Credit card bill"})
    assert renamed.status_code == 200
    assert (await client.patch(f"{URL}/{card['id']}", json={"type": "expense"})).status_code == 409
    assert (await client.delete(f"{URL}/{card['id']}")).status_code == 409


async def test_category_with_children_cannot_be_deleted(client: httpx.AsyncClient) -> None:
    parent = (await client.post(URL, json={"name": "Kids", "type": "expense"})).json()
    await client.post(URL, json={"name": "School", "type": "expense", "parent_id": parent["id"]})
    assert (await client.delete(f"{URL}/{parent['id']}")).status_code == 409


async def test_category_cannot_be_its_own_parent(client: httpx.AsyncClient) -> None:
    rent = await _by_name(client, "Rent")
    response = await client.patch(f"{URL}/{rent['id']}", json={"parent_id": rent["id"]})
    assert response.status_code == 422


async def test_delete_regular_category(client: httpx.AsyncClient) -> None:
    created = (await client.post(URL, json={"name": "Pets", "type": "expense"})).json()
    assert (await client.delete(f"{URL}/{created['id']}")).status_code == 204
    assert "Pets" not in [c["name"] for c in await _all(client)]
