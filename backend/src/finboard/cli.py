"""`finboard` command line.

finboard serve     migrate, then serve API + built SPA on one port
finboard worker    run a Celery worker
finboard beat      run the housekeeping scheduler (staged-import expiry, stale jobs, old jobs)
finboard migrate   apply database migrations
finboard dev       migrate, then API (reload) + worker (auto-restart) + Vite, Ctrl-C stops all
finboard openapi   print the OpenAPI schema (used to generate frontend types)
finboard init      write a secret key (FINBOARD_SECRET_KEY) to .env if there isn't one
finboard parsers   list installed statement parsers (and any that failed to load)
finboard inspect-layout <pdf>   print a statement's structure with contents masked
finboard ai fetch-model  download the embedding model once (optional AI, ARCHITECTURE §18)
finboard ai eval-suggestions  compare embeddings with the trigram baseline -> docs/ai-eval.md
finboard ai eval         golden Ask questions against the real provider -> docs/ai-eval.md
finboard demo-data synthetic sample transactions and limits for the local user (empty DB only)
"""

import argparse
import getpass
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path

from finboard.core.config import get_settings
from finboard.core.logging import configure_logging

BACKEND_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
IS_WINDOWS = sys.platform == "win32"


def _migrate(*, backup_first: bool = False) -> None:
    from finboard.db import migrate

    settings = get_settings()
    url = settings.migration_database_url
    if backup_first and settings.backup_before_migrate and migrate.needs_backup(url):
        try:
            migrate.backup(url, settings.backup_dir, revision=migrate.current_revision(url))
        except migrate.BackupFailed as exc:
            sys.exit(
                f"Not migrating: the backup before migrating failed ({exc}). Fix pg_dump, or set "
                "FINBOARD_BACKUP_BEFORE_MIGRATE=false to migrate without a backup."
            )
    migrate.upgrade(url)


def cmd_migrate(_args: argparse.Namespace) -> None:
    _migrate()


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    settings = get_settings()
    if not args.no_migrate:
        _migrate(backup_first=True)  # a pg_dump first when the schema is behind (§16)
    uvicorn.run(
        "finboard.main:create_app",
        factory=True,
        host=args.host or settings.host,
        port=args.port or settings.port,
        log_config=None,
        proxy_headers=False,
        workers=args.workers,
    )


def cmd_worker(args: argparse.Namespace) -> None:
    from finboard.jobs.celery_app import celery_app

    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    queues = "default,parse,ai" if settings.ai_suggestions else "default,parse"
    argv = ["worker", f"--loglevel={settings.log_level}", f"--queues={queues}"]
    # Celery's prefork pool isn't supported on Windows hosts (OQ-24); hard time limits then
    # only apply when the worker runs in Docker.
    argv.append("--pool=solo" if IS_WINDOWS else f"--concurrency={args.concurrency}")
    celery_app.worker_main(argv)


def cmd_beat(_args: argparse.Namespace) -> None:
    """The housekeeping scheduler (ARCHITECTURE §6). Run exactly one."""
    from finboard.jobs.celery_app import celery_app

    settings = get_settings()
    configure_logging(settings.log_level, json=settings.log_json)
    schedule = Path(settings.blob_dir).parent / "celerybeat-schedule"
    celery_app.start(["beat", f"--loglevel={settings.log_level}", f"--schedule={schedule}"])


def run_dev_worker() -> None:
    """Entry point for the auto-restarting dev worker (see cmd_dev)."""
    cmd_worker(argparse.Namespace(concurrency=1))


def init_secret_key(env_file: Path) -> bool:
    """Append FINBOARD_SECRET_KEY to `env_file` unless it is already configured.

    Returns True if a key was written. The key encrypts statement passwords on their way to the
    worker (ADR-0027); losing it only affects passwords in flight (they live 120 s).
    """
    if os.environ.get("FINBOARD_SECRET_KEY"):
        return False
    existing = env_file.read_text(encoding="utf-8") if env_file.is_file() else ""
    if any(line.strip().startswith("FINBOARD_SECRET_KEY=") for line in existing.splitlines()):
        return False
    line = f"FINBOARD_SECRET_KEY={secrets.token_urlsafe(32)}\n"
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(prefix + line)
    return True


def cmd_init(args: argparse.Namespace) -> None:
    env_file = Path(args.env_file)
    if init_secret_key(env_file):
        print(f"Wrote FINBOARD_SECRET_KEY to {env_file} (keep this file private).")
    else:
        print("FINBOARD_SECRET_KEY is already set; nothing to do.")


def cmd_parsers(_args: argparse.Namespace) -> None:
    from finboard.parsers.registry import default_registry, is_fallback

    registry = default_registry(tuple(get_settings().extra_parsers))
    for parser in registry.all():
        flag = "  (fallback)" if is_fallback(parser) else ""
        print(f"{parser.id:28} {parser.version:9} {parser.name}{flag}")
    for failure in registry.failures:
        print(f"FAILED  {failure.source}: {failure.reason}", file=sys.stderr)


def cmd_inspect_layout(args: argparse.Namespace) -> None:
    from finboard.parsers.inspect import inspect_layout
    from finboard.parsers.sdk import DocumentError, PasswordRequired, open_document

    data = Path(args.pdf).read_bytes()
    password: str | None = None
    while True:
        try:
            doc = open_document(data, password=password)
            break
        except PasswordRequired as exc:
            if not sys.stdin.isatty():
                sys.exit(f"{exc.user_message}; run this in a terminal to enter the password.")
            if password is not None:
                print(exc.user_message, file=sys.stderr)
            password = getpass.getpass("Statement password (not stored): ")
        except DocumentError as exc:
            sys.exit(exc.user_message)
    with doc:
        print(inspect_layout(doc, tables=not args.no_tables))
    print(
        "\nEvery digit is shown as 9 and every letter as X. Check the output before sharing it.",
        file=sys.stderr,
    )


def cmd_ai_fetch_model(args: argparse.Namespace) -> None:
    """The one explicit download for category suggestions (ADR-0030)."""
    from finboard.ai.embeddings import EmbeddingsUnavailable, fetch

    settings = get_settings()
    model = args.model or settings.embed_model
    try:
        path = fetch(model, Path(settings.model_dir))
    except EmbeddingsUnavailable as exc:
        sys.exit(str(exc))
    print(f"Downloaded {model} to {path}. Embedding now runs offline.")


def cmd_ai_eval_suggestions(args: argparse.Namespace) -> None:
    """Compare embedding models with the trigram baseline (M3a) and write the report."""
    from finboard.ai import evaluation
    from finboard.ai.embeddings import EmbeddingsUnavailable, embed

    settings = get_settings()
    methods: dict[str, evaluation.Similarity] = {"trigram": evaluation.trigram_matrix}
    for model in args.models or [
        "sentence-transformers/all-MiniLM-L6-v2",
        "BAAI/bge-small-en-v1.5",
    ]:

        def run(texts: object, model: str = model) -> list[list[float]]:
            return embed(list(texts), model=model, cache_dir=Path(settings.model_dir))  # type: ignore[call-overload]

        methods[model] = evaluation.embedding_matrix_for(run)
    try:
        report = evaluation.report(evaluation.compare(methods))
    except EmbeddingsUnavailable as exc:
        sys.exit(f"{exc} (fetch each model first: finboard ai fetch-model --model NAME)")
    out = Path(args.out)
    existing = out.read_text("utf-8") if out.exists() else ""
    marker = "<!-- ask-eval:start -->"  # keep the Ask report (finboard ai eval) below
    kept = existing[existing.index(marker) :] if marker in existing else ""
    out.write_text(report.rstrip("\n") + ("\n\n" + kept if kept else "\n"), encoding="utf-8")
    print(report)


def cmd_ai_eval(args: argparse.Namespace) -> None:
    """Golden questions through the real Ask pipeline and provider (M4a). Manual: it calls
    the configured provider, about 30-90 requests."""
    import asyncio

    from finboard.db.engine import create_engine, create_sessionmaker
    from finboard.services.ai import AiConfig
    from finboard.services.ask import default_llm_factory
    from finboard.services.ask_eval import report, run_eval, write_section

    settings = get_settings()
    if args.model:
        field = "ai_model" if settings.ai_ask == "gemini" else "ollama_model"
        settings = settings.model_copy(update={field: args.model})
    factory = default_llm_factory(settings)
    if factory is None:
        sys.exit("Set FINBOARD_AI_ASK=gemini (and FINBOARD_GEMINI_API_KEY) or ollama first.")
    config = AiConfig.from_settings(settings)

    async def run() -> str:
        engine = create_engine(settings)
        try:
            outcomes = await run_eval(
                create_sessionmaker(engine),
                config,
                factory,
                delay=args.delay,
                limit=args.limit,
                progress=lambda o: print(
                    f"{'ok ' if o.correct else 'NO '} {o.path or '-':4} {o.latency_ms:>6} ms  "
                    f"{o.question}",
                    file=sys.stderr,
                ),
            )
        finally:
            await engine.dispose()
        return report(outcomes, model=config.ai_model, ask_sql=config.ask_sql)

    section = asyncio.run(run())
    write_section(Path(args.out), section)
    print(section)


def cmd_demo_data(_args: argparse.Namespace) -> None:
    """Load the synthetic handover sample into the local user (an empty Finboard only)."""
    import asyncio

    from finboard.db.engine import create_engine, create_sessionmaker
    from finboard.db.uow import unit_of_work
    from finboard.domain.errors import FinboardError
    from finboard.services.demo import load_demo
    from finboard.services.users import ensure_local_user

    async def run() -> None:
        engine = create_engine(get_settings())
        try:
            sessionmaker = create_sessionmaker(engine)
            principal = await ensure_local_user(sessionmaker)
            async with unit_of_work(sessionmaker, principal.user_id) as uow:
                result = await load_demo(uow)
        finally:
            await engine.dispose()
        print(
            f"Loaded {result.transactions} demo transactions in {result.accounts} accounts "
            f"({result.first_month:%b %Y} to {result.last_month:%b %Y}) and "
            f"{result.budgets} monthly limits."
        )

    try:
        asyncio.run(run())
    except FinboardError as exc:
        sys.exit(exc.detail)


def cmd_dev(_args: argparse.Namespace) -> None:
    if init_secret_key(BACKEND_DIR / ".env"):
        print("Created a dev FINBOARD_SECRET_KEY in backend/.env (needed to unlock statements).")
        get_settings.cache_clear()
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
    serve.add_argument(
        "--workers", type=int, default=1, help="API processes (stateless, ARCHITECTURE §14)"
    )
    serve.set_defaults(func=cmd_serve)

    ai = sub.add_parser("ai", help="optional AI features (ARCHITECTURE §18)")
    ai_sub = ai.add_subparsers(dest="ai_command", required=True)
    fetch_model = ai_sub.add_parser(
        "fetch-model", help="download the embedding model once (then everything runs offline)"
    )
    fetch_model.add_argument("--model", help="default: FINBOARD_EMBED_MODEL")
    fetch_model.set_defaults(func=cmd_ai_fetch_model)
    eval_suggestions = ai_sub.add_parser(
        "eval-suggestions", help="compare embedding models with the trigram baseline"
    )
    eval_suggestions.add_argument("--models", nargs="*", help="embedding models to compare")
    eval_suggestions.add_argument("--out", default="../docs/ai-eval.md")
    eval_suggestions.set_defaults(func=cmd_ai_eval_suggestions)
    ask_eval = ai_sub.add_parser(
        "eval", help="run the golden Ask questions against the configured provider"
    )
    ask_eval.add_argument("--model", help="provider model id (default: FINBOARD_AI_MODEL)")
    ask_eval.add_argument("--delay", type=float, default=4.0, help="seconds between questions")
    ask_eval.add_argument("--limit", type=int, help="only the first N questions")
    ask_eval.add_argument("--out", default="../docs/ai-eval.md")
    ask_eval.set_defaults(func=cmd_ai_eval)
    sub.add_parser("beat", help="run the housekeeping scheduler (one only)").set_defaults(
        func=cmd_beat
    )
    worker = sub.add_parser("worker", help="run a background worker")
    worker.add_argument("--concurrency", type=int, default=2)
    worker.set_defaults(func=cmd_worker)

    sub.add_parser("migrate", help="apply database migrations").set_defaults(func=cmd_migrate)
    sub.add_parser("dev", help="API + worker + Vite with reload").set_defaults(func=cmd_dev)
    sub.add_parser("openapi", help="print the OpenAPI schema").set_defaults(func=cmd_openapi)

    init = sub.add_parser("init", help="create a secret key in .env")
    init.add_argument("--env-file", default=".env", help="file to write (default: ./.env)")
    init.set_defaults(func=cmd_init)

    sub.add_parser("parsers", help="list installed parsers").set_defaults(func=cmd_parsers)
    sub.add_parser(
        "demo-data", help="load synthetic sample data (screenshots, trying Finboard out)"
    ).set_defaults(func=cmd_demo_data)

    inspect = sub.add_parser(
        "inspect-layout", help="print a statement's structure with contents masked"
    )
    inspect.add_argument("pdf", help="path to the statement PDF (read locally, never uploaded)")
    inspect.add_argument("--no-tables", action="store_true", help="skip table detection")
    inspect.set_defaults(func=cmd_inspect_layout)

    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
