from fastapi import APIRouter

from finboard.api.routers import accounts, categories, health, jobs, me, settings

api_router = APIRouter()
for module in (health, me, accounts, categories, jobs, settings):
    api_router.include_router(module.router)
