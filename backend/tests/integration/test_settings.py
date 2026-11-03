import httpx

URL = "/api/v1/settings"


async def test_defaults(client: httpx.AsyncClient) -> None:
    assert (await client.get(URL)).json() == {"theme": "system"}


async def test_update_theme_is_per_user(client: httpx.AsyncClient) -> None:
    response = await client.patch(URL, json={"theme": "dark"})
    assert response.json() == {"theme": "dark"}
    assert (await client.get(URL)).json() == {"theme": "dark"}
    assert (await client.get(URL, headers={"X-Test-User": "bob"})).json() == {"theme": "system"}


async def test_invalid_theme(client: httpx.AsyncClient) -> None:
    assert (await client.patch(URL, json={"theme": "pink"})).status_code == 422
