from fastapi import APIRouter

from finboard.api.routers import (
    accounts,
    budgets,
    categories,
    dashboard,
    data,
    health,
    imports,
    jobs,
    me,
    parsers,
    review,
    rules,
    settings,
    transactions,
    transfers,
)

api_router = APIRouter()
for module in (
    health,
    me,
    accounts,
    categories,
    jobs,
    settings,
    imports,
    parsers,
    transactions,
    review,
    transfers,
    rules,
    dashboard,
    budgets,
    data,
):
    api_router.include_router(module.router)
