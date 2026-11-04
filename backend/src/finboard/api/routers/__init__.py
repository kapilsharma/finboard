from fastapi import APIRouter

from finboard.api.routers import (
    accounts,
    categories,
    health,
    imports,
    jobs,
    me,
    parsers,
    settings,
)

api_router = APIRouter()
for module in (health, me, accounts, categories, jobs, settings, imports, parsers):
    api_router.include_router(module.router)
