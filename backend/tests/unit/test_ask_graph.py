"""M4a: the spec builder (golden SQL), chart choice, answers, and the graph with a fake model:
retries, the SQL path switch, and that no state ever holds result rows."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from finboard.ai.results import Chart, Column, Result, Shape, answer, choose_chart, inr
from finboard.ai.spec import CategoryPath, QuerySpec, SpecError, build

CATS = [CategoryPath("Dining out"), CategoryPath("Groceries"), CategoryPath("Swiggy", "Dining out")]
TODAY = date(2026, 11, 5)


def test_builder_golden_sql() -> None:
    spec = QuerySpec(
        metric="spending",
        categories=["dining out", "Groceries"],
        group_by=["month", "category"],
        last_months=6,
    )
    built = build(spec, today=TODAY, categories=CATS, accounts=["Account A"])
    assert built.sql == (
        "SELECT month, category, COALESCE(SUM(signed_amount), 0) AS spending FROM ai_txn "
        "WHERE type = ANY(:types) AND ((category = :c0 OR parent_category = :c0) OR "
        "(category = :c1 OR parent_category = :c1)) AND date >= :start AND date <= :end "
        "GROUP BY month, category ORDER BY month, category"
    )
    assert built.params == {
        "types": ["expense"],
        "c0": "Dining out",
        "c1": "Groceries",
        "start": date(2026, 6, 1),
        "end": TODAY,
    }
    assert [c.kind for c in built.columns] == ["month", "text", "money"]


def test_builder_metrics_and_filters() -> None:
    net = build(
        QuerySpec(metric="net", accounts=["account a"], merchant="50%_off", top=3),
        today=TODAY,
        categories=CATS,
        accounts=["Account A"],
    )
    assert "CASE WHEN type = 'income' THEN signed_amount ELSE -signed_amount END" in net.sql
    assert net.params["types"] == ["income", "expense"]
    assert net.params["accounts"] == ["Account A"]
    assert net.params["merchant"] == "%50\\%\\_OFF%"  # LIKE wildcards escaped
    assert net.sql.endswith("LIMIT 3")
    child = build(
        QuerySpec(categories=["Dining out > Swiggy"]), today=TODAY, categories=CATS, accounts=[]
    )
    assert "(category = :c0 AND parent_category = :p0)" in child.sql


@pytest.mark.parametrize(
    "spec",
    [
        QuerySpec(categories=["Rent"]),
        QuerySpec(accounts=["Account Z"]),
        QuerySpec(start=date(2026, 9, 1), end=date(2026, 8, 1)),
    ],
)
def test_builder_rejects_unknown_names(spec: QuerySpec) -> None:
    with pytest.raises(SpecError):
        build(spec, today=TODAY, categories=CATS, accounts=["Account A"])


def test_spec_is_closed() -> None:
    with pytest.raises(ValueError):
        QuerySpec.model_validate({"metric": "spending", "sql": "DROP TABLE x"})
    with pytest.raises(ValueError):
        QuerySpec.model_validate({"group_by": ["month", "month"]})


@pytest.mark.parametrize(
    ("columns", "rows", "hint", "expected"),
    [
        ([("month", "month"), ("v", "money")], 6, None, Chart("bar", "month", None, "v")),
        ([("month", "month"), ("v", "money")], 6, "line", Chart("line", "month", None, "v")),
        ([("month", "month"), ("v", "money")], 24, None, Chart("line", "month", None, "v")),
        ([("category", "text"), ("v", "money")], 5, "line", Chart("bar", "category", None, "v")),
        (
            [("category", "text"), ("month", "month"), ("v", "money")],
            12,
            None,
            Chart("grouped_bar", "month", "category", "v"),
        ),
        ([("v", "money")], 1, None, Chart("table", None, None, "v")),
        ([("a", "text"), ("b", "text")], 3, None, Chart("table")),
        ([("month", "month"), ("v", "money")], 0, None, Chart("table")),
    ],
)
def test_chart_from_shape(
    columns: list[tuple[str, str]], rows: int, hint: str | None, expected: Chart
) -> None:
    assert choose_chart(Shape(columns, rows), hint) == expected


def test_answer_and_inr() -> None:
    assert inr(Decimal("142702.04")) == "₹1,42,702.04"
    assert inr(Decimal("-93.94")) == "\u2212₹93.94"
    assert inr(Decimal("12345678.00")) == "₹1,23,45,678.00"
    result = Result(
        [Column("month", "month"), Column("spending", "money")],
        [("2026-08", Decimal("10.50")), ("2026-09", Decimal("4.50"))],
    )
    assert answer(result, "Spending") == "Spending: ₹15.00 in total across 2 rows."
    assert answer(Result([Column("v", "money")], []), "X") == "X: no matching transactions."


# ---------------------------------------------------------------- the graph, with a fake model

langgraph = pytest.importorskip("langgraph")

from finboard.ai import graph  # noqa: E402
from finboard.ai.catalog import load  # noqa: E402
from finboard.ai.llm import AccountAlias, LlmReply, LlmRequest  # noqa: E402
from finboard.ai.sandbox import SandboxRows  # noqa: E402

SECRET_ROWS = [("2026-09", Decimal("31337.42"))]


class Fake:
    model = "fake"

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.requests: list[LlmRequest] = []

    async def complete(self, request: LlmRequest) -> LlmReply:
        self.requests.append(request)
        return LlmReply(self.replies.pop(0), 10, 2)


def _ctx(llm: Fake, *, allow_sql: bool = True) -> graph.AskContext:
    async def run_spec(built: Any) -> Result:
        return Result(built.columns, [(r[0], r[1]) for r in SECRET_ROWS][: len(built.columns)])

    async def run_sql(sqlite: str) -> Result:
        from finboard.ai import sandbox

        rows = SandboxRows(
            [("2026-09-01", "2026-09", "Account A", "savings", "Groceries", None, "expense",
              "debit", Decimal("31337.42"), "SECRETMART")],
            [],
        )  # fmt: skip
        return sandbox.run(rows, sqlite)

    return graph.AskContext(
        llm=llm,
        catalog=load(),
        categories=CATS,
        accounts=[AccountAlias(alias="Account A", type="savings")],
        today=TODAY,
        allow_sql=allow_sql,
        run_spec=run_spec,
        run_sql=run_sql,
    )


async def test_no_state_ever_holds_rows() -> None:
    llm = Fake(
        json.dumps({"kind": "sql"}),
        json.dumps({"sql": "SELECT nope FROM ai_txn"}),
        json.dumps({"sql": "SELECT merchant, SUM(signed_paise) AS s_paise FROM ai_txn GROUP BY 1"}),
    )
    ctx = _ctx(llm)
    states: list[dict[str, Any]] = []
    final = await graph.run(ctx, "What did I spend where?", on_state=states.append)
    assert final["status"] == "ok" and final["retries"] == 1
    assert ctx.store.get(final["result_id"] or "").rows == [("SECRETMART", Decimal("31337.42"))]
    for state in states:
        dumped = json.dumps(state, default=str)
        assert "SECRETMART" not in dumped and "31337" not in dumped
    assert llm.requests[2].retry_hint == "unknown column nope"


async def test_sql_path_off_asks_to_rephrase() -> None:
    llm = Fake(json.dumps({"kind": "sql"}))
    final = await graph.run(_ctx(llm, allow_sql=False), "Something custom?")
    assert final["status"] == "clarify" and final["clarification"] == graph.NO_SQL
    assert len(llm.requests) == 1
    assert '"kind": "sql"' not in llm.requests[0].model_dump_json()  # option not offered


async def test_bad_spec_retries_then_works() -> None:
    llm = Fake(
        json.dumps({"kind": "spec", "spec": {"categories": ["Rent"]}}),
        json.dumps({"kind": "spec", "spec": {"categories": ["Groceries"], "group_by": ["month"]}}),
    )
    final = await graph.run(_ctx(llm), "Rent?")
    assert final["status"] == "ok" and final["retries"] == 1
    assert "unknown category 'Rent'" in (llm.requests[1].retry_hint or "")
    assert final["chart"] == {"kind": "bar", "x": "month", "series": None, "y": "spending"}
    assert final["tokens_in"] == 20
