"""Server mode: sign-up, sign-in, sessions, CSRF token, rate limits and quotas (M8, ADR-0041).

These run the real `SessionBackend` against Redis. The tenancy suite runs against it too:
`FINBOARD_TEST_AUTH=session pytest tests/integration/tenancy`.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from finboard.core.config import Mode, Settings
from finboard.main import create_app

from .conftest import BASE_URL, CLIENT_HEADERS, RecordingJobQueue
from .imports_helpers import statement

API = "/api/v1"
PASSWORD = "a long enough passphrase"
ACCOUNT = {"name": "Savings", "type": "savings"}


def server_settings(settings: Settings, **overrides: object) -> Settings:
    return settings.model_copy(
        update={"mode": Mode.SERVER, "public_url": BASE_URL, "signup": "open", **overrides}
    )


@pytest.fixture(autouse=True)
async def _clean_redis(settings: Settings) -> AsyncIterator[None]:
    """Sessions and rate-limit counters must not leak from one test into the next."""
    yield
    from redis.asyncio import Redis

    redis = Redis.from_url(settings.redis_url)
    try:
        for pattern in ("rl:*", "session:*", "user-sessions:*"):
            keys = [key async for key in redis.scan_iter(pattern)]
            if keys:
                await redis.delete(*keys)
    finally:
        await redis.aclose()


@pytest.fixture
async def make_app(
    settings: Settings, job_queue: RecordingJobQueue, owner_engine: AsyncEngine
) -> AsyncIterator[object]:
    """Start a server-mode app with the given setting overrides."""
    stack: list[object] = []

    async def start(**overrides: object) -> FastAPI:
        application = create_app(server_settings(settings, **overrides), job_queue=job_queue)
        context = application.router.lifespan_context(application)
        await context.__aenter__()
        stack.append(context)
        return application

    yield start
    for context in reversed(stack):
        await context.__aexit__(None, None, None)  # type: ignore[attr-defined]


def browser(application: FastAPI) -> httpx.AsyncClient:
    """A client that keeps cookies, like a browser tab."""
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url=BASE_URL, headers=CLIENT_HEADERS
    )


async def signup(client: httpx.AsyncClient, username: str, password: str = PASSWORD) -> str:
    response = await client.post(
        f"{API}/auth/signup", json={"username": username, "password": password}
    )
    assert response.status_code == 201, response.text
    token: str = response.json()["csrf_token"]
    return token


@pytest.fixture
async def server(make_app: object) -> FastAPI:
    application: FastAPI = await make_app()  # type: ignore[operator]
    return application


# ---------------------------------------------------------------- sign-up and sign-in


async def test_nobody_is_signed_in_at_first(server: FastAPI) -> None:
    async with browser(server) as c:
        for path in ("/me", "/accounts", "/dashboard/months", "/transactions"):
            response = await c.get(f"{API}{path}")
            assert response.status_code == 401, path
            assert response.json()["code"] == "unauthenticated"
        # What the sign-in page needs is public.
        meta = (await c.get(f"{API}/meta")).json()
        assert meta["mode"] == "server" and meta["signup_open"] is True
        assert (await c.get(f"{API}/health/ready")).status_code == 200


async def test_signup_signs_in_and_provisions_the_account(server: FastAPI) -> None:
    async with browser(server) as c:
        response = await c.post(
            f"{API}/auth/signup",
            json={"username": " Carol ", "display_name": "Carol D", "password": PASSWORD},
        )
        assert response.status_code == 201
        assert response.json()["username"] == "carol"

        cookie = response.headers["set-cookie"].lower()
        assert cookie.startswith("finboard_session=")
        assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
        assert "secure" not in cookie  # plain http on loopback only (see the https test)

        me = (await c.get(f"{API}/me")).json()
        assert (me["username"], me["display_name"], me["mode"]) == ("carol", "Carol D", "server")
        assert me["csrf_token"] == response.json()["csrf_token"]
        # A new account starts with the default categories, like the local user.
        assert len((await c.get(f"{API}/categories")).json()["items"]) > 10


async def test_https_public_url_gives_a_secure_host_cookie(make_app: object) -> None:
    application = await make_app(public_url="https://finboard.example.com")  # type: ignore[operator]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="https://finboard.example.com",
        headers=CLIENT_HEADERS,
    ) as c:
        response = await c.post(
            f"{API}/auth/signup", json={"username": "carol", "password": PASSWORD}
        )
        assert response.status_code == 201, response.text
        cookie = response.headers["set-cookie"].lower()
        assert cookie.startswith("__host-finboard_session=") and "secure" in cookie
        assert (await c.get(f"{API}/me")).status_code == 200


async def test_the_password_is_stored_as_argon2id_only(
    server: FastAPI, owner_engine: AsyncEngine
) -> None:
    async with browser(server) as c:
        await signup(c, "carol")
    async with owner_engine.connect() as conn:
        stored = await conn.scalar(
            text("SELECT password_hash FROM app_user WHERE username = 'carol'")
        )
    assert stored.startswith("$argon2id$") and PASSWORD not in stored


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"username": "carol", "password": "short"}, 422, "validation_failed"),
        ({"username": "carolcarol", "password": "carolcarol"}, 422, "validation_failed"),
        ({"username": "c", "password": PASSWORD}, 422, "invalid_request"),
        ({"username": "has space", "password": PASSWORD}, 422, "validation_failed"),
        ({"username": "../etc", "password": PASSWORD}, 422, "validation_failed"),
    ],
)
async def test_signup_validation(
    server: FastAPI, body: dict[str, str], status: int, code: str
) -> None:
    async with browser(server) as c:
        response = await c.post(f"{API}/auth/signup", json=body)
        assert (response.status_code, response.json()["code"]) == (status, code)


async def test_usernames_are_unique_whatever_the_case(server: FastAPI) -> None:
    async with browser(server) as c:
        await signup(c, "carol")
    async with browser(server) as c:
        response = await c.post(
            f"{API}/auth/signup", json={"username": "CAROL", "password": PASSWORD}
        )
        assert (response.status_code, response.json()["code"]) == (409, "conflict")


async def test_signup_is_closed_unless_the_operator_opens_it(make_app: object) -> None:
    application = await make_app(signup="closed")  # type: ignore[operator]
    async with browser(application) as c:
        assert (await c.get(f"{API}/meta")).json()["signup_open"] is False
        response = await c.post(
            f"{API}/auth/signup", json={"username": "carol", "password": PASSWORD}
        )
        assert (response.status_code, response.json()["code"]) == (403, "signup_closed")


async def test_login_logout_and_a_second_browser(server: FastAPI) -> None:
    async with browser(server) as first:
        await signup(first, "carol")
    async with browser(server) as second:
        response = await second.post(
            f"{API}/auth/login", json={"username": "Carol", "password": PASSWORD}
        )
        assert response.status_code == 200
        assert (await second.get(f"{API}/me")).json()["username"] == "carol"

        assert (await second.post(f"{API}/auth/logout")).status_code == 204
        assert (await second.get(f"{API}/me")).status_code == 401


async def test_a_stolen_cookie_stops_working_after_logout(server: FastAPI) -> None:
    async with browser(server) as c:
        await signup(c, "carol")
        stolen = dict(c.cookies)
        await c.post(f"{API}/auth/logout")
    async with browser(server) as thief:
        thief.cookies.update(stolen)
        assert (await thief.get(f"{API}/me")).status_code == 401


async def test_wrong_password_and_unknown_user_look_the_same(server: FastAPI) -> None:
    async with browser(server) as c:
        await signup(c, "carol")
    async with browser(server) as c:
        wrong = await c.post(f"{API}/auth/login", json={"username": "carol", "password": "x" * 12})
        unknown = await c.post(
            f"{API}/auth/login", json={"username": "nobody", "password": "x" * 12}
        )
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json() == unknown.json()
        assert wrong.json()["code"] == "invalid_credentials"
        assert "set-cookie" not in wrong.headers


async def test_a_user_without_a_password_cannot_sign_in(
    server: FastAPI, owner_engine: AsyncEngine
) -> None:
    """The `local` user of a local-mode database has no password until the operator sets one."""
    async with browser(server) as c:
        await signup(c, "carol")
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE app_user SET password_hash = NULL"))
    async with browser(server) as c:
        response = await c.post(f"{API}/auth/login", json={"username": "carol", "password": ""})
        assert response.status_code == 422
        response = await c.post(
            f"{API}/auth/login", json={"username": "carol", "password": PASSWORD}
        )
        assert response.status_code == 401


async def test_a_switched_off_account_cannot_sign_in(
    server: FastAPI, owner_engine: AsyncEngine
) -> None:
    async with browser(server) as c:
        await signup(c, "carol")
    async with owner_engine.begin() as conn:
        await conn.execute(text("UPDATE app_user SET is_active = false"))
    async with browser(server) as c:
        response = await c.post(
            f"{API}/auth/login", json={"username": "carol", "password": PASSWORD}
        )
        assert response.status_code == 401


# ---------------------------------------------------------------- CSRF token


async def test_changes_need_the_sessions_csrf_token(server: FastAPI) -> None:
    async with browser(server) as c:
        token = await signup(c, "carol")

        missing = await c.post(f"{API}/accounts", json=ACCOUNT)
        assert (missing.status_code, missing.json()["code"]) == (403, "csrf_check_failed")
        wrong = await c.post(f"{API}/accounts", json=ACCOUNT, headers={"X-CSRF-Token": "nope"})
        assert wrong.status_code == 403
        assert (await c.get(f"{API}/accounts")).json()["items"] == []

        ok = await c.post(f"{API}/accounts", json=ACCOUNT, headers={"X-CSRF-Token": token})
        assert ok.status_code == 201


async def test_another_users_csrf_token_is_no_use(server: FastAPI) -> None:
    async with browser(server) as carol, browser(server) as dave:
        await signup(carol, "carol")
        daves = await signup(dave, "dave")
        response = await carol.post(
            f"{API}/accounts", json=ACCOUNT, headers={"X-CSRF-Token": daves}
        )
        assert response.status_code == 403


# ---------------------------------------------------------------- isolation, end to end


async def test_two_signed_in_users_see_only_their_own_data(server: FastAPI) -> None:
    async with browser(server) as carol, browser(server) as dave:
        carols = {"X-CSRF-Token": await signup(carol, "carol")}
        daves = {"X-CSRF-Token": await signup(dave, "dave")}
        created = await carol.post(f"{API}/accounts", json=ACCOUNT, headers=carols)
        account = created.json()["id"]

        assert (await dave.get(f"{API}/accounts")).json()["items"] == []
        assert (await dave.get(f"{API}/accounts/{account}")).status_code == 404
        assert (await dave.delete(f"{API}/accounts/{account}", headers=daves)).status_code == 404
        assert len((await carol.get(f"{API}/accounts")).json()["items"]) == 1


# ---------------------------------------------------------------- passwords


async def test_changing_the_password_ends_the_other_sessions(server: FastAPI) -> None:
    new = "another long passphrase"
    async with browser(server) as here, browser(server) as elsewhere:
        token = {"X-CSRF-Token": await signup(here, "carol")}
        await elsewhere.post(f"{API}/auth/login", json={"username": "carol", "password": PASSWORD})
        assert (await elsewhere.get(f"{API}/me")).status_code == 200

        wrong = await here.post(
            f"{API}/auth/password",
            json={"current_password": "not it at all", "new_password": new},
            headers=token,
        )
        assert wrong.status_code == 422
        weak = await here.post(
            f"{API}/auth/password",
            json={"current_password": PASSWORD, "new_password": "short"},
            headers=token,
        )
        assert weak.status_code == 422

        changed = await here.post(
            f"{API}/auth/password",
            json={"current_password": PASSWORD, "new_password": new},
            headers=token,
        )
        assert changed.status_code == 204
        assert (await here.get(f"{API}/me")).status_code == 200  # this session stays
        assert (await elsewhere.get(f"{API}/me")).status_code == 401

    async with browser(server) as c:
        old = await c.post(f"{API}/auth/login", json={"username": "carol", "password": PASSWORD})
        assert old.status_code == 401
        fresh = await c.post(f"{API}/auth/login", json={"username": "carol", "password": new})
        assert fresh.status_code == 200


# ---------------------------------------------------------------- sessions expire


async def test_a_session_ends_at_its_maximum_age(make_app: object) -> None:
    application = await make_app(session_max_days=0)  # type: ignore[operator]
    async with browser(application) as c:
        await signup(c, "carol")
        assert (await c.get(f"{API}/me")).status_code == 401


# ---------------------------------------------------------------- rate limits and quotas


async def test_sign_in_locks_after_repeated_wrong_passwords(make_app: object) -> None:
    application = await make_app(login_max_failures=3)  # type: ignore[operator]
    async with browser(application) as c:
        await signup(c, "carol")
    async with browser(application) as c:
        for _ in range(3):
            response = await c.post(
                f"{API}/auth/login", json={"username": "carol", "password": "x" * 12}
            )
            assert response.status_code == 401
        # Even the right password is refused until the window ends.
        locked = await c.post(f"{API}/auth/login", json={"username": "carol", "password": PASSWORD})
        assert (locked.status_code, locked.json()["code"]) == (429, "rate_limited")
        assert int(locked.headers["retry-after"]) > 0


async def test_a_successful_sign_in_clears_the_failure_count(make_app: object) -> None:
    application = await make_app(login_max_failures=3)  # type: ignore[operator]
    async with browser(application) as c:
        await signup(c, "carol")
    async with browser(application) as c:
        for _ in range(2):
            for password in ("x" * 12, "y" * 12, PASSWORD):
                response = await c.post(
                    f"{API}/auth/login", json={"username": "carol", "password": password}
                )
        assert response.status_code == 200


async def test_signups_per_address_are_limited(make_app: object) -> None:
    application = await make_app(signup_per_ip_per_hour=2)  # type: ignore[operator]
    for name in ("carol", "dave"):
        async with browser(application) as c:
            await signup(c, name)
    async with browser(application) as c:
        response = await c.post(
            f"{API}/auth/signup", json={"username": "erin", "password": PASSWORD}
        )
        assert response.status_code == 429


async def test_requests_per_user_are_limited_per_user(make_app: object) -> None:
    application = await make_app(rate_limit_per_minute=5)  # type: ignore[operator]
    async with browser(application) as carol, browser(application) as dave:
        await signup(carol, "carol")
        await signup(dave, "dave")
        statuses = [(await carol.get(f"{API}/accounts")).status_code for _ in range(7)]
        assert statuses[:5] == [200] * 5 and statuses[5:] == [429, 429]
        assert (await dave.get(f"{API}/accounts")).status_code == 200  # dave isn't slowed down


async def test_storage_quota_refuses_an_upload_that_would_pass_it(make_app: object) -> None:
    data, _ = statement(1, 6)
    application = await make_app(storage_quota_bytes=len(data) + 10)  # type: ignore[operator]
    async with browser(application) as c:
        token = {"X-CSRF-Token": await signup(c, "carol")}
        files = {"file": ("s.pdf", data, "application/pdf")}
        assert (await c.post(f"{API}/imports", files=files, headers=token)).status_code == 202
        full = await c.post(f"{API}/imports", files=files, headers=token)
        assert (full.status_code, full.json()["code"]) == (413, "storage_quota_exceeded")


async def test_uploads_per_hour_are_limited(make_app: object) -> None:
    data, _ = statement(1, 6)
    application = await make_app(upload_rate_per_hour=1)  # type: ignore[operator]
    async with browser(application) as c:
        token = {"X-CSRF-Token": await signup(c, "carol")}
        files = {"file": ("s.pdf", data, "application/pdf")}
        assert (await c.post(f"{API}/imports", files=files, headers=token)).status_code == 202
        assert (await c.post(f"{API}/imports", files=files, headers=token)).status_code == 429


# ---------------------------------------------------------------- local mode is unchanged


async def test_local_mode_has_no_sign_in(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"{API}/meta")).json()["signup_open"] is False
    for path, body in (
        ("/auth/login", {"username": "alice", "password": PASSWORD}),
        ("/auth/signup", {"username": "carol", "password": PASSWORD}),
        ("/auth/logout", None),
    ):
        response = await client.post(f"{API}{path}", json=body)
        assert response.status_code == 404, path
    me = (await client.get(f"{API}/me")).json()
    assert me["mode"] == "local" and me["csrf_token"] is None
