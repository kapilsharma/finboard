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
from finboard.parsers.registry import ParserRegistry
from finboard.services.accounts import AccountService
from finboard.services.ai import AiConfig, AiSettingsService, SuggestionService
from finboard.services.ask import AskService
from finboard.services.budgets import BudgetService
from finboard.services.categories import CategoryService
from finboard.services.dashboard import DashboardService
from finboard.services.data import DataService
from finboard.services.imports import ImportLimits, ImportService
from finboard.services.jobs import JobQueue, JobService
from finboard.services.review import ReviewService
from finboard.services.rules import RuleService
from finboard.services.settings import SettingsService
from finboard.services.transactions import TransactionService
from finboard.services.transfers import TransferService


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


def get_registry(request: Request) -> ParserRegistry:
    registry: ParserRegistry = request.app.state.registry
    return registry


def get_import_service(
    request: Request, uow: UowDep, queue: Annotated[JobQueue, Depends(get_job_queue)]
) -> ImportService:
    state = request.app.state
    return ImportService(
        uow,
        blobs=state.blobs,
        queue=queue,
        registry=state.registry,
        limits=ImportLimits.from_settings(state.settings),
        secrets=state.secrets,
        embed_after_commit=AiConfig.from_settings(state.settings).uses_embeddings,
    )


QueueDep = Annotated[JobQueue, Depends(get_job_queue)]


def get_rule_service(uow: UowDep, queue: QueueDep) -> RuleService:
    return RuleService(uow, queue)


def get_review_service(uow: UowDep, queue: QueueDep) -> ReviewService:
    return ReviewService(uow, RuleService(uow, queue))


def get_transfer_service(uow: UowDep, queue: QueueDep) -> TransferService:
    return TransferService(uow, queue)


def get_transaction_service(uow: UowDep, queue: QueueDep) -> TransactionService:
    return TransactionService(uow, queue)


def get_dashboard_service(uow: UowDep) -> DashboardService:
    return DashboardService(uow)


def get_budget_service(uow: UowDep) -> BudgetService:
    return BudgetService(uow)


def get_data_service(request: Request, uow: UowDep, queue: QueueDep) -> DataService:
    return DataService(uow, queue, request.app.state.blobs)


def get_ai_settings_service(request: Request, uow: UowDep, queue: QueueDep) -> AiSettingsService:
    return AiSettingsService(uow, AiConfig.from_settings(request.app.state.settings), queue)


def get_ask_service(request: Request, uow: UowDep) -> AskService:
    settings = request.app.state.settings
    return AskService(uow, AiConfig.from_settings(settings), request.app.state.llm_factory)


def get_suggestion_service(request: Request, uow: UowDep) -> SuggestionService:
    return SuggestionService(uow, AiConfig.from_settings(request.app.state.settings))


SettingsDep = Annotated[Settings, Depends(get_settings)]
AiSettingsServiceDep = Annotated[AiSettingsService, Depends(get_ai_settings_service)]
AskServiceDep = Annotated[AskService, Depends(get_ask_service)]
SuggestionServiceDep = Annotated[SuggestionService, Depends(get_suggestion_service)]
DataServiceDep = Annotated[DataService, Depends(get_data_service)]
DashboardServiceDep = Annotated[DashboardService, Depends(get_dashboard_service)]
BudgetServiceDep = Annotated[BudgetService, Depends(get_budget_service)]
RuleServiceDep = Annotated[RuleService, Depends(get_rule_service)]
ReviewServiceDep = Annotated[ReviewService, Depends(get_review_service)]
TransferServiceDep = Annotated[TransferService, Depends(get_transfer_service)]
TransactionServiceDep = Annotated[TransactionService, Depends(get_transaction_service)]
RegistryDep = Annotated[ParserRegistry, Depends(get_registry)]
ImportServiceDep = Annotated[ImportService, Depends(get_import_service)]
AccountServiceDep = Annotated[AccountService, Depends(get_account_service)]
CategoryServiceDep = Annotated[CategoryService, Depends(get_category_service)]
SettingsServiceDep = Annotated[SettingsService, Depends(get_settings_service)]
JobServiceDep = Annotated[JobService, Depends(get_job_service)]
