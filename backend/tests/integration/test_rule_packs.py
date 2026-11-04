"""Rule packs (YAML/JSON): no account ids leak, and they round-trip (ARCHITECTURE §9)."""

import json

import httpx
import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal

from .categorisation_helpers import API, account, category_id, clear_rules, create_rule

BOB = {"X-Test-User": "bob"}


async def export(client: httpx.AsyncClient, fmt: str = "yaml", **kw: object) -> str:
    response = await client.get(f"{API}/rules/export", params={"format": fmt}, **kw)  # type: ignore[arg-type]
    assert response.status_code == 200, response.text
    assert "attachment" in response.headers["content-disposition"]
    return response.text


async def test_export_leaks_no_account_ids_and_round_trips(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> None:
    await clear_rules(client)
    acc = await account(sessionmaker, alice)
    parent = (
        await client.post(f"{API}/categories", json={"name": "Home", "type": "expense"})
    ).json()["id"]
    child = (
        await client.post(
            f"{API}/categories", json={"name": "Repairs", "type": "expense", "parent_id": parent}
        )
    ).json()["id"]
    await create_rule(
        client, pattern="URBAN COMPANY", category_id=child, account_id=str(acc), direction="debit"
    )
    await create_rule(
        client,
        match_kind="regex",
        pattern=r"\bSIP\b",
        category_id=await category_id(client, "Investments"),
        amount_min="500.00",
        label="Monthly SIPs",
        enabled=False,
    )

    text = await export(client)
    assert str(acc) not in text and "account" not in text
    pack = yaml.safe_load(text)
    assert pack["finboard_rule_pack"] == 1
    assert pack["rules"][0] == {
        "match_kind": "contains",
        "pattern": "URBAN COMPANY",
        "category": "Home / Repairs",
        "category_type": "expense",
        "direction": "debit",
    }
    assert pack["rules"][1]["amount_min"] == "500.00" and pack["rules"][1]["enabled"] is False
    assert json.loads(await export(client, "json")) == pack

    # Bob imports Alice's pack: the missing categories are created from their paths.
    await clear_rules(client, headers=BOB)
    response = await client.post(
        f"{API}/rules/import", json={"content": text, "mode": "replace"}, headers=BOB
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"added": 2, "skipped": 0, "replaced": 0, "categories_created": 2}
    assert yaml.safe_load(await export(client, headers=BOB)) == pack

    # Merging the same pack again adds nothing.
    again = await client.post(f"{API}/rules/import", json={"content": text}, headers=BOB)
    assert again.json()["added"] == 0 and again.json()["skipped"] == 2


async def test_replace_swaps_and_merge_appends(client: httpx.AsyncClient) -> None:
    await clear_rules(client)
    food = await category_id(client, "Dining out")
    await create_rule(client, pattern="OLD", category_id=food)
    pack = {
        "finboard_rule_pack": 1,
        "rules": [
            {
                "match_kind": "contains",
                "pattern": "NEW",
                "category": "Dining out",
                "category_type": "expense",
            }
        ],
    }
    merged = await client.post(f"{API}/rules/import", json={"content": json.dumps(pack)})
    assert merged.json()["added"] == 1
    assert [r["pattern"] for r in (await client.get(f"{API}/rules")).json()["items"]] == [
        "OLD",
        "NEW",
    ]
    replaced = await client.post(
        f"{API}/rules/import", json={"content": json.dumps(pack), "mode": "replace"}
    )
    assert replaced.json()["replaced"] == 2 and replaced.json()["added"] == 1
    assert [r["pattern"] for r in (await client.get(f"{API}/rules")).json()["items"]] == ["NEW"]


async def test_starter_pack_merges_into_existing_rules(client: httpx.AsyncClient) -> None:
    before = len((await client.get(f"{API}/rules")).json()["items"])
    response = await client.post(f"{API}/rules/starter-pack")
    assert response.json()["added"] == 0 and response.json()["skipped"] == before
    await clear_rules(client)
    response = await client.post(f"{API}/rules/starter-pack")
    assert response.json()["added"] == before


async def test_bad_packs_are_refused_without_changes(client: httpx.AsyncClient) -> None:
    before = (await client.get(f"{API}/rules")).json()["items"]
    bad = [
        "not: [valid",  # broken YAML
        "!!python/object/apply:os.system ['echo hi']",  # safe_load refuses tags
        "finboard_rule_pack: 2\nrules: []",
        "finboard_rule_pack: 1\nrules:\n- {match_kind: regex, pattern: '(', category: X, category_type: expense}",
        "finboard_rule_pack: 1\nrules:\n- {match_kind: contains, pattern: A, category: X, category_type: expense, amount_min: 1.5}",
        "finboard_rule_pack: 1\nrules:\n- {match_kind: contains, pattern: A, category: 'A / B / C', category_type: expense}",
        "finboard_rule_pack: 1\nrules:\n- {match_kind: contains, pattern: A, category: X, category_type: expense, account_id: x}",
    ]
    for content in bad:
        response = await client.post(
            f"{API}/rules/import", json={"content": content, "mode": "replace"}
        )
        assert response.status_code == 422, (content, response.text)
    assert (await client.get(f"{API}/rules")).json()["items"] == before
