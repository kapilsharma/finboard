import uuid

import httpx
import pytest

URL = "/api/v1/accounts"


async def _create(client: httpx.AsyncClient, **fields: object) -> dict[str, object]:
    body = {"name": "ICICI Savings", "type": "savings", **fields}
    response = await client.post(URL, json=body)
    assert response.status_code == 201, response.text
    data: dict[str, object] = response.json()
    return data


async def test_create_and_get(client: httpx.AsyncClient) -> None:
    created = await _create(client, institution="ICICI Bank", masked_number="0042")
    assert created["currency"] == "INR"
    assert created["active"] is True
    fetched = (await client.get(f"{URL}/{created['id']}")).json()
    assert fetched == created


async def test_list_puts_active_accounts_first(client: httpx.AsyncClient) -> None:
    await _create(client, name="Zeta", active=False)
    await _create(client, name="alpha")
    await _create(client, name="Beta")
    names = [a["name"] for a in (await client.get(URL)).json()["items"]]
    assert names == ["alpha", "Beta", "Zeta"]


async def test_names_are_unique_case_insensitively(client: httpx.AsyncClient) -> None:
    await _create(client, name="Kotak Savings")
    response = await client.post(URL, json={"name": "  kotak savings ", "type": "savings"})
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


@pytest.mark.parametrize(
    "body",
    [
        {"name": "X", "type": "savings", "masked_number": "12345"},  # last 4 only
        {"name": "X", "type": "savings", "masked_number": "12a4"},
        {"name": "", "type": "savings"},
        {"name": "X", "type": "piggy_bank"},
        {"name": "X", "type": "savings", "colour": "red"},
        {"name": "X", "type": "savings", "unexpected": 1},
    ],
)
async def test_invalid_input_is_422(client: httpx.AsyncClient, body: dict[str, object]) -> None:
    response = await client.post(URL, json=body)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


async def test_patch_updates_only_sent_fields(client: httpx.AsyncClient) -> None:
    created = await _create(client, institution="ICICI Bank", masked_number="1111")
    response = await client.patch(
        f"{URL}/{created['id']}", json={"masked_number": None, "active": False}
    )
    assert response.status_code == 200
    updated = response.json()
    assert updated["masked_number"] is None
    assert updated["active"] is False
    assert updated["institution"] == "ICICI Bank"


async def test_patch_rejects_null_for_required_fields(client: httpx.AsyncClient) -> None:
    created = await _create(client)
    response = await client.patch(f"{URL}/{created['id']}", json={"name": None})
    assert response.status_code == 422


async def test_rename_to_existing_name_conflicts(client: httpx.AsyncClient) -> None:
    await _create(client, name="HSBC Savings")
    other = await _create(client, name="Yes Savings")
    response = await client.patch(f"{URL}/{other['id']}", json={"name": "hsbc savings"})
    assert response.status_code == 409


async def test_delete(client: httpx.AsyncClient) -> None:
    created = await _create(client)
    assert (await client.delete(f"{URL}/{created['id']}")).status_code == 204
    assert (await client.get(f"{URL}/{created['id']}")).status_code == 404


async def test_unknown_id_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"{URL}/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
