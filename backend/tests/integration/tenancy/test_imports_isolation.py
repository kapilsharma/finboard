"""User B can't see, change, commit or roll back user A's imports (ADR-0025)."""

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from finboard.auth import Principal

from ..conftest import RecordingJobQueue
from ..imports_helpers import API, create_account, parsed, statement

BOB = {"X-Test-User": "bob"}


@pytest.fixture
async def alices_imports(client: httpx.AsyncClient, job_queue: RecordingJobQueue) -> dict[str, str]:
    data, expected = statement(seed=50, rows=5)
    account = await create_account(client, expected.account_hint)
    staged = await parsed(client, job_queue, data)
    committed = await parsed(client, job_queue, statement(seed=52, rows=4)[0])
    response = await client.post(
        f"{API}/imports/{committed['id']}/commit",
        json={"create_account": {"name": "Other", "type": "savings"}},
    )
    assert response.status_code == 200
    return {"staged": staged["id"], "committed": committed["id"], "account": account["id"]}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/imports/{staged}", None),
        ("POST", "/imports/{staged}/unlock", {"password": "x"}),
        ("POST", "/imports/{staged}/reparse", {}),
        ("PATCH", "/imports/{staged}/rows/0", {"include": False}),
        ("POST", "/imports/{staged}/commit", {}),
        ("DELETE", "/imports/{staged}", None),
        ("POST", "/imports/{committed}/rollback", None),
    ],
)
async def test_other_users_imports_are_404(
    client: httpx.AsyncClient,
    alices_imports: dict[str, str],
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    url = API + path.format(**alices_imports)
    response = await client.request(method, url, json=body, headers=BOB)
    assert response.status_code == 404
    # …and Alice's imports are untouched.
    assert (await client.get(f"{API}/imports/{alices_imports['staged']}")).json()[
        "status"
    ] == "parsed"
    assert (await client.get(f"{API}/imports/{alices_imports['committed']}")).json()[
        "status"
    ] == "committed"


async def test_history_is_per_user(
    client: httpx.AsyncClient, alices_imports: dict[str, str]
) -> None:
    assert (await client.get(f"{API}/imports", headers=BOB)).json()["items"] == []


async def test_bob_cannot_reparse_into_alices_account(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, alices_imports: dict[str, str]
) -> None:
    bobs = await parsed(client, job_queue, statement(seed=53, rows=2)[0], headers=BOB)
    response = await client.post(
        f"{API}/imports/{bobs['id']}/reparse",
        json={"account_id": alices_imports["account"]},
        headers=BOB,
    )
    assert response.status_code == 422


async def test_same_statement_is_new_for_each_user(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, alices_imports: dict[str, str]
) -> None:
    """Fingerprints are unique per user, so Alice's rows never make Bob's look like duplicates."""
    data, _ = statement(seed=52, rows=4)
    bobs = await parsed(client, job_queue, data, headers=BOB)
    assert bobs["file_already_imported"] is None
    response = await client.post(
        f"{API}/imports/{bobs['id']}/commit",
        json={"create_account": {"name": "Bob's", "type": "savings"}},
        headers=BOB,
    )
    assert response.json()["result"]["inserted"] == 4


async def test_rls_hides_staged_rows_and_transactions(
    app_engine: AsyncEngine, alices_imports: dict[str, str], bob: Principal, alice: Principal
) -> None:
    for user, expected_min in ((alice, 1), (bob, 0)):
        async with app_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user.user_id)}
            )
            for table in ("import_batch", "staged_row", "txn", "import_row"):
                count = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
                assert (count >= expected_min) if expected_min else count == 0, (user, table)
