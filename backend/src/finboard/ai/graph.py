"""Ask Finboard as a LangGraph state graph (ADR-0032):

understand → (spec) execute_spec ─┐
           → (sql) generate → guard → execute_sql ─┤→ chart → answer
           → clarify                                 ┘
with at most 2 retries in total, each carrying a locally written hint.

The state holds the question, the spec or SQL, hints, a result id and a shape summary. Rows
live in the request's `ResultStore`, never in the state (ADR-0030 §4), so even a tracer or
checkpointer has no data to see. Everything with side effects (the LLM, Postgres, the
sandbox) is injected through `AskContext`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from finboard.ai.catalog import Catalog
from finboard.ai.llm import AccountAlias, LlmClient, LlmRequest, parse_json
from finboard.ai.results import Result, ResultStore, Shape, answer, choose_chart
from finboard.ai.sandbox import SandboxError
from finboard.ai.spec import BuiltQuery, CategoryPath, QuerySpec, SpecError, build
from finboard.ai.sql_guard import GuardRejected, guard

MAX_RETRIES = 2
GIVE_UP = "Finboard couldn't turn that into a query. Try naming the categories or months."
NO_SQL = (
    "That needs a custom query, which is switched off on this server. "
    "Try asking for a metric by month, category, account or merchant."
)


class AskState(TypedDict, total=False):
    question: str
    route: str
    path: Literal["spec", "sql"] | None
    spec: dict[str, Any] | None
    sql: str | None  # the model's SQL after the guard (Postgres dialect)
    sqlite: str | None
    chart_hint: str | None
    hint: str | None  # locally written; the only feedback the model ever gets
    retries: int
    result_id: str | None
    shape: dict[str, Any] | None
    chart: dict[str, Any] | None
    title: str | None
    answer: str | None
    clarification: str | None
    status: Literal["ok", "clarify", "failed"]
    error: str | None
    tokens_in: int
    tokens_out: int


@dataclass
class AskContext:
    llm: LlmClient
    catalog: Catalog
    categories: list[CategoryPath]
    accounts: list[AccountAlias]
    today: date
    allow_sql: bool
    run_spec: Callable[[BuiltQuery], Awaitable[Result]]
    run_sql: Callable[[str], Awaitable[Result]]
    store: ResultStore = field(default_factory=ResultStore)
    max_retries: int = MAX_RETRIES

    def request(self, task: Literal["understand", "generate_sql"], s: AskState) -> LlmRequest:
        return LlmRequest(
            task=task,
            question=s["question"],
            catalog=self.catalog.text,
            category_paths=[c.path for c in self.categories],
            accounts=self.accounts,
            today=self.today,
            allow_sql=self.allow_sql,
            retry_hint=s.get("hint"),
        )

    def build(self, spec: QuerySpec) -> BuiltQuery:
        return build(
            spec,
            today=self.today,
            categories=self.categories,
            accounts=[a.alias for a in self.accounts],
        )


def _retry(s: AskState, ctx: AskContext, hint: str, route: str) -> AskState:
    retries = s.get("retries", 0)
    if retries >= ctx.max_retries:
        return {"route": "fail", "status": "failed", "error": GIVE_UP, "hint": hint}
    return {"route": route, "hint": hint[:300], "retries": retries + 1}


def _usage(s: AskState, tokens_in: int, tokens_out: int) -> AskState:
    return {
        "tokens_in": s.get("tokens_in", 0) + tokens_in,
        "tokens_out": s.get("tokens_out", 0) + tokens_out,
    }


def title_for(spec: QuerySpec, built: BuiltQuery) -> str:
    title = {"count": "Number of transactions", "net": "Net saving"}.get(
        spec.metric, spec.metric.capitalize()
    )
    if built.filters:
        title += " on " + ", ".join(built.filters)
    if spec.group_by:
        title += " by " + " and ".join(spec.group_by)
    if built.start and built.end:
        title += f", {built.start:%d %b %Y} to {built.end:%d %b %Y}"
    elif built.start:
        title += f", from {built.start:%d %b %Y}"
    elif built.end:
        title += f", until {built.end:%d %b %Y}"
    return title


def make_graph(ctx: AskContext) -> Any:
    async def understand(s: AskState) -> AskState:
        reply = await ctx.llm.complete(ctx.request("understand", s))
        update = _usage(s, reply.tokens_in, reply.tokens_out)
        try:
            data = parse_json(reply.text)
        except ValueError:
            return {
                **update,
                **_retry(s, ctx, "reply with one JSON object as described", "understand"),
            }
        kind = data.get("kind")
        if kind == "clarify" and isinstance(data.get("question"), str):
            return {**update, "route": "clarify", "status": "clarify",
                    "clarification": data["question"][:300]}  # fmt: skip
        if kind == "sql":
            if not ctx.allow_sql:
                return {**update, "route": "clarify", "status": "clarify", "clarification": NO_SQL}
            return {**update, "route": "generate", "path": "sql", "hint": None}
        if kind == "spec":
            try:
                spec = QuerySpec.model_validate(data.get("spec"))
            except ValidationError as exc:
                fields = sorted({".".join(map(str, e["loc"])) for e in exc.errors()})
                hint = f"the spec had invalid fields: {', '.join(fields)[:200]}"
                return {**update, **_retry(s, ctx, hint, "understand")}
            return {**update, "route": "spec", "path": "spec",
                    "spec": spec.model_dump(mode="json"), "hint": None}  # fmt: skip
        return {
            **update,
            **_retry(s, ctx, 'set "kind" to "spec", "sql" or "clarify"', "understand"),
        }

    async def execute_spec(s: AskState) -> AskState:
        spec = QuerySpec.model_validate(s["spec"])
        try:
            built = ctx.build(spec)
        except SpecError as exc:
            return _retry(s, ctx, str(exc), "understand")
        result = await ctx.run_spec(built)
        return {
            "route": "chart",
            "result_id": ctx.store.put(result),
            "shape": result.shape().as_dict(),
            "chart_hint": spec.chart,
            "title": title_for(spec, built),
        }

    async def generate(s: AskState) -> AskState:
        reply = await ctx.llm.complete(ctx.request("generate_sql", s))
        update = _usage(s, reply.tokens_in, reply.tokens_out)
        try:
            data = parse_json(reply.text)
            sql = data["sql"]
            if not isinstance(sql, str):
                raise ValueError
        except (ValueError, KeyError):
            return {**update, **_retry(s, ctx, 'reply with {"sql": "..."}', "generate")}
        hint = data.get("chart")
        return {**update, "route": "guard", "sql": sql,
                "chart_hint": hint if isinstance(hint, str) else None}  # fmt: skip

    async def guard_node(s: AskState) -> AskState:
        try:
            guarded = guard(s.get("sql") or "")
        except GuardRejected as exc:
            return _retry(s, ctx, str(exc), "generate")
        return {"route": "execute_sql", "sql": guarded.postgres, "sqlite": guarded.sqlite}

    async def execute_sql(s: AskState) -> AskState:
        try:
            result = await ctx.run_sql(s.get("sqlite") or "")
        except SandboxError as exc:
            return _retry(s, ctx, exc.hint, "generate")
        return {
            "route": "chart",
            "result_id": ctx.store.put(result),
            "shape": result.shape().as_dict(),
            "title": "Answer",
        }

    async def chart(s: AskState) -> AskState:
        shape = Shape.from_dict(s["shape"] or {})
        return {"chart": choose_chart(shape, s.get("chart_hint")).as_dict()}

    async def answer_node(s: AskState) -> AskState:
        result = ctx.store.get(s["result_id"] or "")
        return {"status": "ok", "answer": answer(result, s.get("title") or "Answer")}

    def route(s: AskState) -> str:
        return s.get("route") or "fail"

    g: Any = StateGraph(AskState)  # its overloads reject typed async nodes
    g.add_node("understand", understand)
    g.add_node("execute_spec", execute_spec)
    g.add_node("generate", generate)
    g.add_node("guard", guard_node)
    g.add_node("execute_sql", execute_sql)
    g.add_node("chart", chart)
    g.add_node("answer", answer_node)
    g.add_edge(START, "understand")
    g.add_conditional_edges(
        "understand",
        route,
        {"spec": "execute_spec", "generate": "generate", "understand": "understand",
         "clarify": END, "fail": END},
    )  # fmt: skip
    g.add_conditional_edges(
        "execute_spec", route, {"chart": "chart", "understand": "understand", "fail": END}
    )
    g.add_conditional_edges(
        "generate", route, {"guard": "guard", "generate": "generate", "fail": END}
    )
    g.add_conditional_edges(
        "guard", route, {"execute_sql": "execute_sql", "generate": "generate", "fail": END}
    )
    g.add_conditional_edges(
        "execute_sql", route, {"chart": "chart", "generate": "generate", "fail": END}
    )
    g.add_edge("chart", "answer")
    g.add_edge("answer", END)
    return g.compile()


async def run(
    ctx: AskContext,
    question: str,
    *,
    on_state: Callable[[dict[str, Any]], None] | None = None,
) -> AskState:
    """Run the graph; `on_state` sees every intermediate state (the tests check none of them
    holds rows)."""
    graph = make_graph(ctx)
    final: dict[str, Any] = {}
    initial: AskState = {"question": question, "retries": 0, "tokens_in": 0, "tokens_out": 0}
    async for state in graph.astream(initial, stream_mode="values"):
        if on_state is not None:
            on_state(state)
        final = state
    if not final.get("status"):
        final["status"] = "failed"
        final["error"] = final.get("error") or GIVE_UP
    return final  # type: ignore[return-value]
