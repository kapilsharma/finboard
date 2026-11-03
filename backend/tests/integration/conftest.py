import asyncio
import uuid
from collections.abc import AsyncIterator, Mapping
from pathlib import Path

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

from finboard.auth import Principal
from finboard.core.config import Settings, get_settings
from finboard.db import migrate
from finboard.db.engine import create_engine, create_sessionmaker
from finboard.db.uow import unit_of_work
from finboard.main import create_app
from finboard.services.users import principal_for, provision_user


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

    async def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        return self.users.get(headers.get("x-test-user", self.default))


class RecordingJobQueue:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, object]] = []

    async def enqueue(self, *, kind: str, job_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.enqueued.append({"kind": kind, "job_id": job_id, "user_id": user_id})


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
def job_queue() -> RecordingJobQueue:
    return RecordingJobQueue()


@pytest.fixture
async def app(
    settings: Settings, alice: Principal, bob: Principal, job_queue: RecordingJobQueue
) -> AsyncIterator[FastAPI]:
    backend = HeaderAuthBackend({"alice": alice, "bob": bob}, default="alice")
    application = create_app(settings, auth_backend=backend, job_queue=job_queue)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://127.0.0.1",
        headers={"X-Finboard-Client": "1"},
    ) as c:
        yield c
