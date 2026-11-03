"""`finboard` command line.

finboard serve     migrate, then serve API + built SPA on one port
finboard worker    run a Celery worker
finboard migrate   apply database migrations
finboard dev       migrate, then API (reload) + worker (auto-restart) + Vite, Ctrl-C stops all
finboard openapi   print the OpenAPI schema (used to generate frontend types)
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from finboard.core.config import get_settings
from finboard.core.logging import configure_logging

BACKEND_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
IS_WINDOWS = sys.platform == "win32"


def _migrate() -> None:
    from finboard.db.migrate import upgrade

    upgrade(get_settings().migration_database_url)


def cmd_migrate(_args: argparse.Namespace) -> None:
    _migrate()


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    settings = get_settings()
    if not args.no_migrate:
        _migrate()
    uvicorn.run(
        "finboard.main:create_app",
        factory=True,
        host=args.host or settings.host,
        port=args.port or settings.port,
        log_config=None,
        proxy_headers=False,
    )


def cmd_worker(args: argparse.Namespace) -> None:
    from finboard.jobs.celery_app import celery_app

    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    argv = ["worker", f"--loglevel={settings.log_level}", "--queues=default,parse"]
    # Celery's prefork pool isn't supported on Windows hosts (OQ-24); hard time limits then
    # only apply when the worker runs in Docker.
    argv.append("--pool=solo" if IS_WINDOWS else f"--concurrency={args.concurrency}")
    celery_app.worker_main(argv)


def run_dev_worker() -> None:
    """Entry point for the auto-restarting dev worker (see cmd_dev)."""
    cmd_worker(argparse.Namespace(concurrency=1))


def cmd_dev(_args: argparse.Namespace) -> None:
    settings = get_settings()
    _migrate()
    src = str(BACKEND_DIR / "src")
    py = sys.executable
    commands: list[tuple[str, list[str], Path]] = [
        (
            "api",
            [
                py,
                "-m",
                "uvicorn",
                "finboard.main:create_app",
                "--factory",
                "--reload",
                "--reload-dir",
                src,
                "--host",
                settings.host,
                "--port",
                str(settings.port),
            ],
            BACKEND_DIR,
        ),
        (
            "worker",
            # watchfiles restarts the worker when Python files change.
            [
                py,
                "-m",
                "watchfiles",
                "--filter",
                "python",
                "--target-type",
                "function",
                "finboard.cli.run_dev_worker",
                src,
            ],
            BACKEND_DIR,
        ),
    ]
    npm = shutil.which("npm")
    if npm and (FRONTEND_DIR / "package.json").is_file():
        commands.append(("web", [npm, "run", "dev"], FRONTEND_DIR))
    else:
        print("frontend: npm or frontend/package.json not found; skipping Vite", file=sys.stderr)

    procs = [subprocess.Popen(cmd, cwd=cwd) for _name, cmd, cwd in commands]  # noqa: S603
    print(
        f"Finboard dev: API http://{settings.host}:{settings.port}/api/docs"
        " · app http://127.0.0.1:5173 · Ctrl-C to stop"
    )
    try:
        for proc in procs:
            proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for proc in procs:
            if proc.poll() is None:
                proc.terminate()
        for proc in procs:
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def cmd_openapi(_args: argparse.Namespace) -> None:
    from finboard.main import create_app

    print(json.dumps(create_app().openapi(), indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="finboard", description="Private personal finance.")
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="migrate, then serve API + SPA")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument("--no-migrate", action="store_true")
    serve.set_defaults(func=cmd_serve)

    worker = sub.add_parser("worker", help="run a background worker")
    worker.add_argument("--concurrency", type=int, default=2)
    worker.set_defaults(func=cmd_worker)

    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=cmd_migrate)
    sub.add_parser("dev", help="API + worker + Vite with reload").set_defaults(func=cmd_dev)
    sub.add_parser("openapi", help="print the OpenAPI schema").set_defaults(func=cmd_openapi)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
