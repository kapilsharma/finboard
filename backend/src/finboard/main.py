"""Application factory. `uvicorn finboard.main:create_app --factory`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartParser
from starlette.responses import Response
from starlette.types import Scope

from finboard import __version__
from finboard.api.errors import install_error_handlers
from finboard.api.middleware import RequestContextMiddleware, SecurityMiddleware
from finboard.api.routers import api_router
from finboard.auth import AuthBackend, LocalSingleUserBackend
from finboard.core.config import Mode, Settings, get_settings
from finboard.core.logging import configure_logging
from finboard.db.engine import create_engine, create_sessionmaker
from finboard.parsers.registry import default_registry
from finboard.services.jobs import JobQueue
from finboard.services.users import ensure_local_user
from finboard.storage.blob import LocalFsBlobStore
from finboard.storage.secrets import RedisSecretStore

PACKAGED_STATIC = Path(__file__).parent / "web" / "static"


class SPAStaticFiles(StaticFiles):
    """Serve the built SPA; unknown non-API paths fall back to index.html (client routing)."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            # Check the URL path: `path` is OS-normalised (backslashes on Windows).
            if exc.status_code == 404 and not scope["path"].startswith("/api/"):
                return await super().get_response("index.html", scope)
            raise


def create_app(
    settings: Settings | None = None,
    *,
    auth_backend: AuthBackend | None = None,
    job_queue: JobQueue | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    if settings.mode is Mode.SERVER:
        raise RuntimeError(
            "FINBOARD_MODE=server needs a real authentication backend, which doesn't exist yet "
            "(planned for M8, see docs/adr/0021). Use FINBOARD_MODE=local."
        )
    configure_logging(settings.log_level, json=settings.log_json)
    # Starlette spools uploads over 1 MB to a temporary file on disk. A statement may be
    # unencrypted, so keep uploads (capped by max_upload_bytes) in memory instead.
    MultiPartParser.spool_max_size = settings.max_upload_bytes + 1024 * 1024

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        sessionmaker = create_sessionmaker(engine)
        redis = Redis.from_url(settings.redis_url)
        app.state.engine = engine
        app.state.sessionmaker = sessionmaker
        app.state.redis = redis
        app.state.blobs = LocalFsBlobStore(settings.blob_dir)
        secret = settings.secret_key.get_secret_value() if settings.secret_key else None
        app.state.secrets = RedisSecretStore(redis, secret) if secret else None
        app.state.registry = default_registry(tuple(settings.extra_parsers))
        if app.state.auth_backend is None:
            app.state.auth_backend = LocalSingleUserBackend(await ensure_local_user(sessionmaker))
        if app.state.job_queue is None:
            from finboard.jobs.celery_app import celery_app
            from finboard.jobs.queue import CeleryJobQueue

            app.state.job_queue = CeleryJobQueue(celery_app)
        try:
            yield
        finally:
            await redis.aclose()
            await engine.dispose()

    app = FastAPI(
        title="Finboard",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.auth_backend = auth_backend
    app.state.job_queue = job_queue

    install_error_handlers(app)
    app.include_router(api_router, prefix="/api/v1")

    static_dir = settings.static_dir or PACKAGED_STATIC
    if (static_dir / "index.html").is_file():
        app.mount("/", SPAStaticFiles(directory=static_dir, html=True), name="spa")

    # Added last = runs first: request context wraps everything, including rejections.
    app.add_middleware(SecurityMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(RequestContextMiddleware)
    return app
