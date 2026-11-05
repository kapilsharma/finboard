"""`finboard ai eval` (ADR-0032 §5): the golden questions through the real Ask pipeline and a
real provider, scored against reference answers on the synthetic demo data.

Runs as a dedicated `ai-eval` user (created on first run, with the demo data), so it never
touches anyone's real data. A question is correct when the model's rows equal the reference
rows (values compared regardless of column names and row order).
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.ai.results import Result
from finboard.ai.spec import QuerySpec, build
from finboard.ai.sql_guard import guard
from finboard.db.uow import unit_of_work
from finboard.domain.errors import AiUnavailable
from finboard.services.ai import ASK_KEY, AiConfig
from finboard.services.ask import AskService, LlmFactory
from finboard.services.demo import load_demo
from finboard.services.users import provision_user

EVAL_USERNAME = "ai-eval"
START, END = "<!-- ask-eval:start -->", "<!-- ask-eval:end -->"
_CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Golden:
    question: str
    spec: dict[str, Any] | None = None
    sql: str | None = None


@dataclass(frozen=True, slots=True)
class Outcome:
    question: str
    reference: str  # spec or sql
    status: str
    path: str | None
    correct: bool
    retries: int
    latency_ms: int
    tokens_in: int
    tokens_out: int
    error: str | None = None


def load_golden() -> tuple[date, list[Golden]]:
    raw = yaml.safe_load(
        resources.files("finboard.ai").joinpath("eval_questions.yaml").read_text("utf-8")
    )
    return date.fromisoformat(raw["today"]), [
        Golden(q["q"], q.get("spec"), q.get("sql")) for q in raw["questions"]
    ]


def _norm(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return repr(value)
    if isinstance(value, int | float | Decimal):
        return str(Decimal(str(value)).quantize(_CENT))
    text = str(value).strip()
    try:
        return str(Decimal(text).quantize(_CENT))
    except ArithmeticError:  # decimal.InvalidOperation: not a number
        return text.casefold()


def same_rows(a: Sequence[Sequence[Any]], b: Sequence[Sequence[Any]]) -> bool:
    def bag(rows: Sequence[Sequence[Any]]) -> Counter[tuple[str, ...]]:
        return Counter(tuple(sorted(_norm(v) for v in row)) for row in rows)

    return bag(a) == bag(b)


async def _eval_user(sm: async_sessionmaker[AsyncSession]) -> Any:
    async with unit_of_work(sm) as uow:
        user = await uow.users.get_by_username(EVAL_USERNAME)
        if user is None:
            user = await provision_user(uow, username=EVAL_USERNAME, display_name="AI eval")
            await uow.commit()
    async with unit_of_work(sm, user.id) as uow:
        if not await uow.dashboard.months():
            await load_demo(uow)
        await uow.settings.set(ASK_KEY, True)
        await uow.commit()
    return user.id


async def _reference(service: AskService, golden: Golden, today: date) -> Result:
    if golden.spec is not None:
        spec = QuerySpec.model_validate(golden.spec)
        categories = await service._categories()
        aliases = [a.alias for a in await service.uow.ask.aliases()]
        return await service.run_spec(
            build(spec, today=today, categories=categories, accounts=aliases)
        )
    return await service.run_sql(guard(golden.sql or "").sqlite)


async def run_eval(
    sm: async_sessionmaker[AsyncSession],
    config: AiConfig,
    llm_factory: LlmFactory,
    *,
    delay: float = 4.0,
    limit: int | None = None,
    progress: Callable[[Outcome], None] | None = None,
) -> list[Outcome]:
    today, questions = load_golden()
    user_id = await _eval_user(sm)
    outcomes: list[Outcome] = []
    for i, golden in enumerate(questions[:limit]):
        if i and delay:
            await asyncio.sleep(delay)  # free-tier rate limits
        async with unit_of_work(sm, user_id) as uow:
            service = AskService(uow, config, llm_factory, today=lambda: today)
            expected = await _reference(service, golden, today)
            started = time.monotonic()
            try:
                answer = await service.ask(golden.question)
            except AiUnavailable as exc:
                outcome = Outcome(
                    golden.question, "spec" if golden.spec else "sql", "unavailable", None,
                    False, 0, int((time.monotonic() - started) * 1000), 0, 0, exc.detail,
                )  # fmt: skip
            else:
                q = answer.query
                got = answer.result.rows if answer.result else None
                outcome = Outcome(
                    golden.question,
                    "spec" if golden.spec else "sql",
                    q.status,
                    q.path,
                    got is not None and same_rows(got, expected.rows),
                    q.retries,
                    q.latency_ms,
                    q.tokens_in or 0,
                    q.tokens_out or 0,
                    q.error or q.clarification,
                )
        outcomes.append(outcome)
        if progress:
            progress(outcome)
    return outcomes


def report(outcomes: Sequence[Outcome], *, model: str, ask_sql: bool) -> str:
    n = len(outcomes) or 1
    correct = sum(o.correct for o in outcomes)
    latencies = sorted(o.latency_ms for o in outcomes) or [0]
    lines = [
        START,
        "# Ask Finboard evaluation (M4a)",
        "",
        "Generated by `finboard ai eval` (ADR-0032 §5) over the synthetic demo data, with",
        f"`today` fixed to the end of the sample. Model: `{model}`; SQL fallback "
        f"{'on' if ask_sql else 'off'}. A question is correct when the answer's rows equal the",
        "reference answer's rows.",
        "",
        f"- **Execution accuracy: {correct}/{len(outcomes)} ({correct / n:.0%})**",
        f"- Path taken: {sum(o.path == 'spec' for o in outcomes)} spec, "
        f"{sum(o.path == 'sql' for o in outcomes)} SQL, "
        f"{sum(o.path is None for o in outcomes)} none (clarify or failed)",
        f"- Retries: {sum(o.retries for o in outcomes)} in total",
        f"- Latency: median {latencies[len(latencies) // 2]} ms, max {latencies[-1]} ms",
        f"- Tokens: {sum(o.tokens_in for o in outcomes)} in, "
        f"{sum(o.tokens_out for o in outcomes)} out",
        "",
        "| # | Question | Reference | Path | Status | Correct | Retries | ms |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for i, o in enumerate(outcomes, 1):
        lines.append(
            f"| {i} | {o.question} | {o.reference} | {o.path or '—'} | {o.status} | "
            f"{'yes' if o.correct else 'no'} | {o.retries} | {o.latency_ms} |"
        )
    lines.append(END)
    return "\n".join(lines) + "\n"


def write_section(path: Path, section: str) -> None:
    """Replace this report's section of the file, keeping the rest (the M3a report)."""
    text = path.read_text("utf-8") if path.exists() else ""
    if START in text and END in text:
        head, rest = text.split(START, 1)
        tail = rest.split(END, 1)[1].lstrip("\n")
        text = head + section + tail
    else:
        text = text.rstrip("\n") + ("\n\n" if text else "") + section
    path.write_text(text, "utf-8")
