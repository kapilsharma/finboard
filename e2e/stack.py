"""Start the app for end-to-end tests: `finboard serve` (API + built SPA) and a worker.

Playwright runs this as its web server. It uses the `finboard_test` database (emptied first),
Redis database 14 and a throwaway blob directory, so it never touches your real data.
Needs Postgres + Redis from deploy/compose.dev.yaml and a built SPA (`npm run build` in
frontend/).
"""

import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
PORT = os.environ.get("E2E_PORT", "8799")
DB = "postgresql+asyncpg://{role}:{role}_dev@127.0.0.1:55432/finboard_test"

ENV = {
    **os.environ,
    "FINBOARD_DATABASE_URL": os.environ.get("E2E_DATABASE_URL", DB.format(role="finboard_app")),
    "FINBOARD_MIGRATION_DATABASE_URL": os.environ.get(
        "E2E_MIGRATION_DATABASE_URL", DB.format(role="finboard_owner")
    ),
    "FINBOARD_REDIS_URL": os.environ.get("E2E_REDIS_URL", "redis://127.0.0.1:56379/14"),
    "FINBOARD_BLOB_DIR": tempfile.mkdtemp(prefix="finboard-e2e-blobs-"),
    "FINBOARD_SECRET_KEY": "e2e-only-secret-key",
    "FINBOARD_LOG_JSON": "false",
    "FINBOARD_LOG_LEVEL": "WARNING",
}

RESET = """
import asyncio, os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
url = os.environ["FINBOARD_MIGRATION_DATABASE_URL"]
assert url.rsplit("/", 1)[-1].endswith("_test"), "e2e only runs against a *_test database"
from finboard.db.migrate import upgrade
upgrade(url)
async def main():
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE app_user CASCADE"))
    await engine.dispose()
asyncio.run(main())
"""


def uv(*args: str) -> list[str]:
    exe = shutil.which("uv")
    if exe is None:
        sys.exit("uv is not on PATH")
    return [exe, "run", "--project", str(BACKEND), *args]


def main() -> None:
    subprocess.run(uv("python", "-c", RESET), env=ENV, cwd=BACKEND, check=True)  # noqa: S603
    procs = [
        subprocess.Popen(  # noqa: S603
            uv("finboard", "serve", "--no-migrate", "--port", PORT), env=ENV, cwd=BACKEND
        ),
        subprocess.Popen(uv("finboard", "worker", "--concurrency", "1"), env=ENV, cwd=BACKEND),  # noqa: S603
    ]

    def stop(*_: object) -> None:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(ENV["FINBOARD_BLOB_DIR"], ignore_errors=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        while all(proc.poll() is None for proc in procs):
            try:
                procs[0].wait(timeout=1)
            except subprocess.TimeoutExpired:
                continue
    finally:
        stop()


if __name__ == "__main__":
    main()
