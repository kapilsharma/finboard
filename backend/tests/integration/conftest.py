import asyncio
import importlib.util
import os
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from finboard.auth import Principal, passwords
from finboard.core.config import Mode, Settings, get_settings
from finboard.db import migrate
from finboard.db.engine import create_engine, create_sessionmaker
from finboard.db.uow import unit_of_work
from finboard.jobs import tasks
from finboard.main import create_app
from finboard.services.users import principal_for, provision_user

# Ask Finboard's tests need the optional `ai` extra (LangGraph, sqlglot); skip them without it.
collect_ignore_glob = (
    []
    if importlib.util.find_spec("langgraph") and importlib.util.find_spec("sqlglot")
    else ["test_ask*.py", "tenancy/test_ask_*.py"]
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    here = Path(__file__).parent
    for item in items:
        if here in item.path.parents:
            item.add_marker(pytest.mark.integration)


class HeaderAuthBackend:
    """Test auth: `X-Test-User: bob` acts as bob; no header acts as the default user."""

    def __init__(self, users: Mapping[str, Principal], default: str) -> None:
        self.users = users
        self.default = default

    async def authenticate(
        self, headers: Mapping[str, str], method: str = "GET"
    ) -> Principal | None:
        return self.users.get(headers.get("x-test-user", self.default))


# FINBOARD_TEST_AUTH=session runs the same tests against the real thing (ROADMAP M8): the app
# starts in server mode with `SessionBackend`, alice and bob sign in through /auth/login, and
# the client turns a test's `X-Test-User: bob` into bob's session cookie and CSRF token. The
# tests themselves don't change; CI runs the tenancy suite both ways.
SESSION_AUTH = os.environ.get("FINBOARD_TEST_AUTH") == "session"
TEST_PASSWORD = "correct horse battery staple"
_TEST_PASSWORD_HASH = passwords.hash_password(TEST_PASSWORD) if SESSION_AUTH else ""
BASE_URL = "http://127.0.0.1"
CLIENT_HEADERS = {"X-Finboard-Client": "1"}


class SessionAuthTransport(httpx.AsyncBaseTransport):
    """Sends each request as the user its `X-Test-User` header names, with that user's real
    session. A name nobody signed in as goes out with no session at all."""

    def __init__(
        self, inner: httpx.AsyncBaseTransport, sessions: Mapping[str, tuple[str, str]], default: str
    ) -> None:
        self.inner = inner
        self.sessions = sessions
        self.default = default

    @property
    def app(self) -> Any:
        return self.inner.app  # type: ignore[attr-defined]  # some tests reach the app this way

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        who = request.headers.get("x-test-user", self.default)
        if "x-test-user" in request.headers:
            del request.headers["x-test-user"]
        if who in self.sessions:
            cookie, csrf = self.sessions[who]
            request.headers["cookie"] = cookie
            request.headers["x-csrf-token"] = csrf
        return await self.inner.handle_async_request(request)


async def _sign_in(
    application: FastAPI, users: Mapping[str, Principal]
) -> dict[str, tuple[str, str]]:
    async with unit_of_work(application.state.sessionmaker) as uow:
        for principal in users.values():
            user = await uow.users.get(principal.user_id)
            assert user is not None
            user.password_hash = _TEST_PASSWORD_HASH
        await uow.commit()
    sessions: dict[str, tuple[str, str]] = {}
    for name in users:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url=BASE_URL,
            headers=CLIENT_HEADERS,
        ) as c:
            response = await c.post(
                "/api/v1/auth/login", json={"username": name, "password": TEST_PASSWORD}
            )
            assert response.status_code == 200, response.text
            cookie = "; ".join(f"{k}={v}" for k, v in response.cookies.items())
            sessions[name] = (cookie, response.json()["csrf_token"])
    return sessions


@asynccontextmanager
async def running_app(
    settings: Settings,
    users: Mapping[str, Principal],
    job_queue: "RecordingJobQueue",
    **kwargs: Any,
) -> AsyncIterator[FastAPI]:
    """The app under test, started. Header-stub auth by default; real sessions with
    FINBOARD_TEST_AUTH=session."""
    if not SESSION_AUTH:
        backend = HeaderAuthBackend(users, default="alice")
        application = create_app(settings, auth_backend=backend, job_queue=job_queue, **kwargs)
        async with application.router.lifespan_context(application):
            yield application
        return
    server = settings.model_copy(
        update={"mode": Mode.SERVER, "public_url": BASE_URL, "rate_limit_per_minute": 0}
    )
    application = create_app(server, job_queue=job_queue, **kwargs)
    async with application.router.lifespan_context(application):
        application.state.test_sessions = await _sign_in(application, users)
        try:
            yield application
        finally:
            for principal in users.values():
                await application.state.sessions.delete_all(principal.user_id)


def api_client(application: FastAPI) -> httpx.AsyncClient:
    transport: httpx.AsyncBaseTransport = httpx.ASGITransport(app=application)
    if SESSION_AUTH:
        transport = SessionAuthTransport(
            transport, application.state.test_sessions, default="alice"
        )
    return httpx.AsyncClient(transport=transport, base_url=BASE_URL, headers=CLIENT_HEADERS)


class RecordingJobQueue:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, object]] = []
        self._done: set[int] = set()
        self.failures: list[Exception] = []

    async def enqueue(
        self,
        *,
        kind: str,
        job_id: uuid.UUID,
        user_id: uuid.UUID,
        secret_ref: str | None = None,
    ) -> None:
        self.enqueued.append(
            {"kind": kind, "job_id": job_id, "user_id": user_id, "secret_ref": secret_ref}
        )

    async def drain(self, kinds: tuple[str, ...] = ("imports.process",)) -> int:
        """Run every queued job of these kinds the way a worker would (the real task body, in
        its own thread and event loop), including jobs queued while draining."""
        ran = 0
        while True:
            pending = [
                i for i, e in enumerate(self.enqueued) if i not in self._done and e["kind"] in kinds
            ]
            if not pending:
                return ran
            entry = self.enqueued[pending[0]]
            self._done.add(pending[0])
            task = TASKS[str(entry["kind"])]
            args = [str(entry["job_id"]), str(entry["user_id"])]
            if entry["kind"] == "imports.process":
                args.append(entry["secret_ref"])  # type: ignore[arg-type]
            try:
                await asyncio.to_thread(task.run, *args)
            except Exception as exc:  # a real worker logs a failed task and carries on
                self.failures.append(exc)
            ran += 1

    async def drain_all(self) -> int:
        return await self.drain(tuple(TASKS))


TASKS = {
    "imports.process": tasks.process_import,
    "rules.apply": tasks.apply_rules,
    "transfers.suggest": tasks.suggest_transfers,
    "data.export": tasks.export_data,
    "data.import": tasks.import_data,
    "data.delete_user_data": tasks.delete_user_data,
    "ai.embed": tasks.embed,
    "ai.embed_all": tasks.embed_all,
}


@pytest.fixture(scope="session")
def settings() -> Settings:
    return get_settings()


@pytest.fixture(scope="session")
async def owner_engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    """Fresh schema for the session: down to base, then up to head (also tests the round trip)."""
    await asyncio.to_thread(migrate.downgrade, settings.migration_database_url, "base")
    await asyncio.to_thread(migrate.upgrade, settings.migration_database_url, "head")
    engine = create_async_engine(settings.migration_database_url)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def app_engine(settings: Settings, owner_engine: AsyncEngine) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(settings)
    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_db(owner_engine: AsyncEngine) -> AsyncIterator[None]:
    yield
    async with owner_engine.begin() as conn:
        await conn.execute(text("TRUNCATE app_user CASCADE"))  # every user table hangs off it


@pytest.fixture
def sessionmaker(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_sessionmaker(app_engine)


async def _make_user(sm: async_sessionmaker[AsyncSession], username: str) -> Principal:
    async with unit_of_work(sm) as uow:
        user = await provision_user(uow, username=username, display_name=username.title())
        await uow.commit()
        return principal_for(user)


@pytest.fixture
async def alice(sessionmaker: async_sessionmaker[AsyncSession]) -> Principal:
    return await _make_user(sessionmaker, "alice")


@pytest.fixture
async def bob(sessionmaker: async_sessionmaker[AsyncSession]) -> Principal:
    return await _make_user(sessionmaker, "bob")


@pytest.fixture
def job_queue(monkeypatch: pytest.MonkeyPatch) -> RecordingJobQueue:
    queue = RecordingJobQueue()
    # Jobs the worker starts (the next waiting upload) go to the same recording queue.
    monkeypatch.setattr(tasks, "job_queue", lambda: queue)
    return queue


@pytest.fixture
async def app(
    settings: Settings, alice: Principal, bob: Principal, job_queue: RecordingJobQueue
) -> AsyncIterator[FastAPI]:
    async with running_app(settings, {"alice": alice, "bob": bob}, job_queue) as application:
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with api_client(app) as c:
        yield c
