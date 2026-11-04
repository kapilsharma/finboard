import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.seed.categories import DEFAULT_CATEGORIES

from .categorisation_helpers import account, add_txns, category_id, create_rule

API = "/api/v1"
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


async def test_merge(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    """Merging moves transactions (taking the target's type), rules and budgets, then deletes
    the source. Where both have a limit change for the same month, the target's wins."""
    cafes = (
        await client.post(f"{API}/categories", json={"name": "Cafes", "type": "expense"})
    ).json()
    dining = await category_id(client, "Dining out")
    acc = await account(sessionmaker, alice)
    ids = await add_txns(
        sessionmaker, alice, acc, [("COFFEE", "200.00", "debit"), ("TEA", "50.00", "debit")]
    )
    await client.post(
        f"{API}/transactions/bulk", json={"ids": [str(i) for i in ids], "category_id": cafes["id"]}
    )
    rule = await create_rule(client, pattern="COFFEE", category_id=cafes["id"])
    for cat, month, limit in (
        (cafes["id"], "2026-08", "900.00"),
        (cafes["id"], "2026-09", "1000.00"),
        (dining, "2026-09", "4000.00"),
    ):
        await client.put(
            f"{API}/budgets/{cat}", json={"effective_from": month, "monthly_limit": limit}
        )

    response = await client.post(f"{API}/categories/{cafes['id']}/merge", json={"into_id": dining})
    assert response.status_code == 200, response.text
    assert response.json() == {
        "into": response.json()["into"],
        "transactions": 2,
        "rules": 1,
        "budgets": 1,  # August moved; September: Dining out's own limit wins
    }
    for txn_id in ids:
        assert (await client.get(f"{API}/transactions/{txn_id}")).json()["category_id"] == dining
    assert (await client.get(f"{API}/rules/{rule['id']}")).json()["category_id"] == dining
    history = (await client.get(f"{API}/budgets/history", params={"category_id": dining})).json()[
        "items"
    ]
    assert [(b["effective_from"], b["monthly_limit"]) for b in history] == [
        ("2026-08-01", "900.00"),
        ("2026-09-01", "4000.00"),
    ]
    names = [c["name"] for c in (await client.get(f"{API}/categories")).json()["items"]]
    assert "Cafes" not in names


async def test_merge_into_another_type_changes_the_transactions_type(
    client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    gifts = (
        await client.post(f"{API}/categories", json={"name": "Gifts in", "type": "income"})
    ).json()
    acc = await account(sessionmaker, alice)
    (txn,) = await add_txns(sessionmaker, alice, acc, [("GIFT", "500.00", "credit")])
    await client.patch(f"{API}/transactions/{txn}", json={"category_id": gifts["id"]})
    refunds = await category_id(client, "Refunds")
    await client.post(f"{API}/categories/{gifts['id']}/merge", json={"into_id": refunds})
    assert (await client.get(f"{API}/transactions/{txn}")).json()["type"] == "income"
    shopping = await category_id(client, "Shopping")
    other = (
        await client.post(f"{API}/categories", json={"name": "Gadgets", "type": "investment"})
    ).json()
    await client.patch(f"{API}/transactions/{txn}", json={"category_id": other["id"]})
    await client.post(f"{API}/categories/{other['id']}/merge", json={"into_id": shopping})
    assert (await client.get(f"{API}/transactions/{txn}")).json()["type"] == "expense"


async def test_merge_refusals(client: httpx.AsyncClient) -> None:
    uncategorized = await category_id(client, "Uncategorized")
    rent = await category_id(client, "Rent")
    system = await client.post(f"{API}/categories/{uncategorized}/merge", json={"into_id": rent})
    assert system.status_code == 409
    itself = await client.post(f"{API}/categories/{rent}/merge", json={"into_id": rent})
    assert itself.status_code == 422
    parent = (
        await client.post(f"{API}/categories", json={"name": "Home", "type": "expense"})
    ).json()
    await client.post(
        f"{API}/categories", json={"name": "Repairs", "type": "expense", "parent_id": parent["id"]}
    )
    with_children = await client.post(
        f"{API}/categories/{parent['id']}/merge", json={"into_id": rent}
    )
    assert with_children.status_code == 409
    other_users = await client.post(
        f"{API}/categories/{rent}/merge",
        json={"into_id": uncategorized},
        headers={"X-Test-User": "bob"},
    )
    assert other_users.status_code == 404
