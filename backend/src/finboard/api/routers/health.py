from fastapi import APIRouter, Request, Response
from sqlalchemy import text

from finboard import __version__
from finboard.api.deps import SettingsDep
from finboard.api.schemas import HealthOut, MetaOut

router = APIRouter(tags=["ops"])


@router.get("/health/live")
async def live() -> HealthOut:
    """The process is up. No dependencies are checked."""
    return HealthOut(status="ok")


@router.get("/health/ready", responses={503: {"model": HealthOut}})
async def ready(request: Request, response: Response) -> HealthOut:
    """Postgres and Redis are reachable, so the instance can take traffic."""
    checks: dict[str, str] = {}
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    try:
        await request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception:
        checks["redis"] = "unavailable"

    healthy = all(v == "ok" for v in checks.values())
    if not healthy:
        response.status_code = 503
    return HealthOut(status="ok" if healthy else "degraded", checks=checks)


@router.get("/meta")
async def meta(settings: SettingsDep) -> MetaOut:
    return MetaOut(version=__version__, api_version="v1", mode=settings.mode.value)
