"""Ask Finboard use cases (ARCHITECTURE §18, ADR-0032): ask, history, pin, pinned widgets.

Off unless the operator made it available (`FINBOARD_AI_ASK`) and the user opted in
(`ai.ask`); otherwise every call is a 404 (`ai_off`). LangGraph is imported lazily, so the
app runs without the `ai` extra.

- The spec path runs builder SQL in Postgres: its own READ ONLY connection, RLS, 3 s.
- The SQL path runs guarded model SQL only in the SQLite sandbox, loaded with this user's
  rows through the same RLS-protected views.
- Results are never stored. Pinned widgets re-run locally with no LLM call; pinned SQL is
  guarded again each time, and a catalog change shows "needs updating".
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

import structlog

from finboard.ai import catalog as catalog_module
from finboard.ai.llm import AccountAlias, LlmClient
from finboard.ai.results import Chart, Result, choose_chart
from finboard.ai.sandbox import SandboxError, SandboxRows
from finboard.ai.spec import BuiltQuery, CategoryPath, QuerySpec, SpecError, build
from finboard.ai.sql_guard import GuardRejected, guard
from finboard.core.config import Settings
from finboard.db.models import AskQuery, DashboardWidget
from finboard.db.uow import UnitOfWork
from finboard.domain.errors import AiFeatureOff, AiUnavailable, Conflict, NotFound
from finboard.services.ai import ASK_KEY, AiConfig, extra_installed

log = structlog.get_logger(__name__)

SPEC_TIMEOUT_MS = 3000
NEEDS_UPDATE = "This chart needs updating: ask the question again."
LlmFactory = Callable[[], LlmClient]


def default_llm_factory(settings: Settings) -> LlmFactory | None:
    """The configured provider (`FINBOARD_AI_ASK`), or None when Ask is off."""
    if settings.ai_ask == "off":
        return None
    provider = settings.ai_ask
    model = settings.ai_model if provider == "gemini" else settings.ollama_model
    key = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None

    def factory() -> LlmClient:
        from finboard.ai.llm import make_client

        return make_client(
            provider,
            model=model,
            timeout=settings.ai_timeout_seconds,
            gemini_api_key=key,
            ollama_url=settings.ollama_url,
        )

    return factory


@dataclass(frozen=True, slots=True)
class AskOutcome:
    query: AskQuery
    result: Result | None
    answer: str | None


@dataclass(frozen=True, slots=True)
class WidgetView:
    widget: DashboardWidget
    query: AskQuery
    result: Result | None
    chart: dict[str, Any] | None
    status: str  # ok, needs_update, failed
    message: str | None = None


class AskService:
    def __init__(
        self,
        uow: UnitOfWork,
        config: AiConfig,
        llm_factory: LlmFactory | None,
        *,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.uow = uow
        self.config = config
        self.llm_factory = llm_factory
        self.today = today
        self._sandbox_rows: SandboxRows | None = None

    # ------------------------------------------------------------ switches

    def available(self) -> bool:
        return self.config.ask != "off" and extra_installed("langgraph")

    async def _require_enabled(self) -> None:
        if not self.available() or (await self.uow.settings.all()).get(ASK_KEY) is not True:
            raise AiFeatureOff("Ask Finboard is off (Settings > AI)")

    # ------------------------------------------------------------ execution

    async def _categories(self) -> list[CategoryPath]:
        cats = await self.uow.categories.list()
        names = {c.id: c.name for c in cats}
        return [CategoryPath(c.name, names.get(c.parent_id) if c.parent_id else None) for c in cats]

    async def _aliases(self) -> list[AccountAlias]:
        return [
            AccountAlias(alias=a.alias, type=a.type, bank=a.institution)
            for a in await self.uow.ask.aliases()
        ]

    async def run_spec(self, built: BuiltQuery) -> Result:
        rows = await self.uow.ask.run_read_only(built.sql, built.params, timeout_ms=SPEC_TIMEOUT_MS)
        return Result(built.columns, rows)

    async def run_sql(self, sqlite_sql: str) -> Result:
        from finboard.ai import sandbox

        if self._sandbox_rows is None:
            txns, budgets = await self.uow.ask.sandbox_rows()
            self._sandbox_rows = SandboxRows(txns, budgets)
        return await asyncio.to_thread(sandbox.run, self._sandbox_rows, sqlite_sql)

    # ------------------------------------------------------------ ask

    async def ask(self, question: str) -> AskOutcome:
        await self._require_enabled()
        if self.llm_factory is None:
            raise AiUnavailable("No AI provider is configured")
        from finboard.ai import graph

        catalog = catalog_module.load()
        llm = self.llm_factory()
        ctx = graph.AskContext(
            llm=llm,
            catalog=catalog,
            categories=await self._categories(),
            accounts=await self._aliases(),
            today=self.today(),
            allow_sql=self.config.ask_sql,
            run_spec=self.run_spec,
            run_sql=self.run_sql,
        )
        started = time.monotonic()
        query = AskQuery(question=question, catalog_version=catalog.version, model=llm.model)
        try:
            state = await graph.run(ctx, question)
        except AiUnavailable as exc:
            query.status, query.error = "failed", exc.detail
            query.latency_ms = int((time.monotonic() - started) * 1000)
            await self.uow.ask.add(query)
            await self.uow.commit()
            raise
        query.latency_ms = int((time.monotonic() - started) * 1000)
        query.status = state.get("status", "failed")
        query.path = state.get("path")
        query.spec = state.get("spec") if query.path == "spec" else None
        query.sql = state.get("sql") if query.path == "sql" and query.status == "ok" else None
        query.chart = state.get("chart")
        query.clarification = state.get("clarification")
        query.error = state.get("error")
        query.retries = state.get("retries", 0)
        query.tokens_in = state.get("tokens_in")
        query.tokens_out = state.get("tokens_out")
        await self.uow.ask.add(query)
        await self.uow.commit()
        result_id = state.get("result_id")
        result = ctx.store.get(result_id) if result_id and query.status == "ok" else None
        log.info(
            "ask.answered",
            status=query.status,
            path=query.path,
            retries=query.retries,
            latency_ms=query.latency_ms,
        )
        return AskOutcome(query, result, state.get("answer"))

    async def history(self) -> list[AskQuery]:
        await self._require_enabled()
        return list(await self.uow.ask.history())

    async def delete_history(self) -> int:
        await self._require_enabled()
        deleted = await self.uow.ask.delete_history()
        await self.uow.commit()
        return deleted

    # ------------------------------------------------------------ pinned widgets

    async def pin(self, query_id: uuid.UUID, title: str | None = None) -> DashboardWidget:
        await self._require_enabled()
        query = await self.uow.ask.get(query_id)
        if query is None:
            raise NotFound("Question not found")
        if query.status != "ok" or query.path is None:
            raise Conflict("Only answered questions can be pinned")
        if await self.uow.ask.widget_for(query_id) is not None:
            raise Conflict("Already pinned")
        widget = await self.uow.ask.add_widget(
            DashboardWidget(ask_query_id=query_id, title=(title or query.question)[:200])
        )
        await self.uow.commit()
        return widget

    async def widgets(self) -> list[WidgetView]:
        """Re-run every pinned question locally (no LLM call)."""
        await self._require_enabled()
        catalog = catalog_module.load()
        categories = await self._categories()
        aliases = [a.alias for a in await self.uow.ask.aliases()]
        views = []
        for widget, query in await self.uow.ask.widgets():
            hint = (query.chart or {}).get("kind")
            try:
                if query.path == "spec":
                    spec = QuerySpec.model_validate(query.spec)
                    built = build(spec, today=self.today(), categories=categories, accounts=aliases)
                    result = await self.run_spec(built)
                elif query.catalog_version != catalog.version:
                    views.append(
                        WidgetView(widget, query, None, None, "needs_update", NEEDS_UPDATE)
                    )
                    continue
                else:
                    result = await self.run_sql(guard(query.sql or "").sqlite)
            except (SpecError, GuardRejected):
                views.append(WidgetView(widget, query, None, None, "needs_update", NEEDS_UPDATE))
                continue
            except SandboxError as exc:
                views.append(WidgetView(widget, query, None, None, "failed", exc.hint))
                continue
            chart: Chart = choose_chart(result.shape(), hint)
            views.append(WidgetView(widget, query, result, chart.as_dict(), "ok"))
        return views

    async def delete_widget(self, widget_id: uuid.UUID) -> None:
        await self._require_enabled()
        if not await self.uow.ask.delete_widget(widget_id):
            raise NotFound("Widget not found")
        await self.uow.commit()
