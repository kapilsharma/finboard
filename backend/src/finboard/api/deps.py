"""FastAPI dependencies: the DI graph every route builds on.

request → get_principal (AuthBackend) → get_uow (session + RLS identity) → services
"""

from collections.abc import AsyncIterator
from typing import Annotated

import structlog
from fastapi import Depends, Request

from finboard.auth import AuthBackend, Principal
from finboard.core.config import Settings
from finboard.db.uow import UnitOfWork, unit_of_work
from finboard.domain.errors import Unauthenticated
from finboard.services.accounts import AccountService
from finboard.services.categories import CategoryService
from finboard.services.jobs import JobQueue, JobService
from finboard.services.settings import SettingsService


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_principal(request: Request) -> Principal:
    backend: AuthBackend = request.app.state.auth_backend
    principal = await backend.authenticate(request.headers)
    if principal is None:
        raise Unauthenticated()
    structlog.contextvars.bind_contextvars(user_id=str(principal.user_id))
    return principal


PrincipalDep = Annotated[Principal, Depends(get_principal)]


async def get_uow(request: Request, principal: PrincipalDep) -> AsyncIterator[UnitOfWork]:
    async with unit_of_work(request.app.state.sessionmaker, principal.user_id) as uow:
        yield uow


UowDep = Annotated[UnitOfWork, Depends(get_uow)]


def get_job_queue(request: Request) -> JobQueue:
    queue: JobQueue = request.app.state.job_queue
    return queue


def get_account_service(uow: UowDep) -> AccountService:
    return AccountService(uow)


def get_category_service(uow: UowDep) -> CategoryService:
    return CategoryService(uow)


def get_settings_service(uow: UowDep) -> SettingsService:
    return SettingsService(uow)


def get_job_service(uow: UowDep, queue: Annotated[JobQueue, Depends(get_job_queue)]) -> JobService:
    return JobService(uow, queue)


SettingsDep = Annotated[Settings, Depends(get_settings)]
AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
CategoryServiceDep = Annotated[CategoryService, Depends(get_category_service)]
SettingsServiceDep = Annotated[SettingsService, Depends(get_settings_service)]
JobServiceDep = Annotated[JobService, Depends(get_job_service)]
