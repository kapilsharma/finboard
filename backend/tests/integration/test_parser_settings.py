"""Per-user parser settings: enable/disable for detection, options validated by the adapter."""

import httpx

from .conftest import RecordingJobQueue
from .fake_parsers import marker_pdf
from .imports_helpers import API, upload

BOB = {"X-Test-User": "bob"}


async def parser(client: httpx.AsyncClient, parser_id: str, **kw: object) -> dict[str, object]:
    items = (await client.get(f"{API}/parsers", **kw)).json()["items"]  # type: ignore[arg-type]
    found: dict[str, object] = next(p for p in items if p["id"] == parser_id)
    return found


async def test_defaults_and_options_schema(client: httpx.AsyncClient) -> None:
    generic = await parser(client, "generic_table")
    assert (
        generic["enabled"] is True
        and generic["options"] == {}
        and generic["options_schema"] is None
    )
    options = await parser(client, "test_options")
    assert options["options"] == {"institution_label": "Options Bank", "skip_zero_rows": True}
    assert "institution_label" in options["options_schema"]["properties"]  # type: ignore[index]


async def test_options_are_validated_and_reach_the_parser(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    bad = await client.patch(
        f"{API}/parsers/test_options", json={"options": {"institution_label": "x" * 41}}
    )
    assert bad.status_code == 422 and "institution_label" in bad.json()["detail"]
    unknown_option_type = await client.patch(
        f"{API}/parsers/test_options", json={"options": {"skip_zero_rows": "maybe"}}
    )
    assert unknown_option_type.status_code == 422
    none_to_set = await client.patch(f"{API}/parsers/generic_table", json={"options": {"x": 1}})
    assert none_to_set.status_code == 422
    assert (await client.patch(f"{API}/parsers/nope", json={"enabled": False})).status_code == 404

    ok = await client.patch(
        f"{API}/parsers/test_options", json={"options": {"institution_label": "My Credit Union"}}
    )
    assert ok.status_code == 200 and ok.json()["options"]["institution_label"] == "My Credit Union"

    created = await upload(client, marker_pdf("OPTIONS-FIXTURE"))
    await job_queue.drain()
    body = (await client.get(f"{API}/imports/{created['id']}")).json()
    assert body["status"] == "parsed" and body["institution"] == "My Credit Union"
    # Bob's settings are his own.
    assert (await parser(client, "test_options", headers=BOB))["options"][
        "institution_label"
    ] == "Options Bank"  # type: ignore[index]


async def test_a_disabled_parser_is_not_detected(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    response = await client.patch(f"{API}/parsers/test_options", json={"enabled": False})
    assert response.status_code == 200 and response.json()["enabled"] is False
    created = await upload(client, marker_pdf("OPTIONS-FIXTURE"))
    await job_queue.drain()
    body = (await client.get(f"{API}/imports/{created['id']}")).json()
    assert body["status"] == "failed"
    assert "test_options" not in {c["id"] for c in body["candidates"]}
    # Bob still has it.
    created = await upload(client, marker_pdf("OPTIONS-FIXTURE"), headers=BOB)
    await job_queue.drain()
    assert (await client.get(f"{API}/imports/{created['id']}", headers=BOB)).json()[
        "status"
    ] == "parsed"
