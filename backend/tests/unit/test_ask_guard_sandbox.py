"""M4a: the SQL guard (attack corpus + Hypothesis) and the SQLite sandbox's own defences."""

from __future__ import annotations

import contextlib
import sqlite3
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sqlglot = pytest.importorskip("sqlglot")

from finboard.ai import sandbox  # noqa: E402
from finboard.ai.sandbox import SandboxError, SandboxRows, describe  # noqa: E402
from finboard.ai.sql_guard import TABLES, GuardRejected, guard  # noqa: E402

ALLOWED = [
    "SELECT month, SUM(signed_paise) AS spent_paise FROM ai_txn WHERE type = 'expense' "
    "GROUP BY month ORDER BY month",
    "SELECT date_trunc('month', date::date) AS m, COUNT(*) FROM ai_txn GROUP BY 1",
    "SELECT extract(year FROM date::date) AS y, SUM(signed_paise) AS s_paise FROM ai_txn GROUP BY 1",
    "SELECT category FROM ai_txn WHERE merchant ILIKE '%swiggy%'",
    "WITH m AS (SELECT month, SUM(signed_paise) AS s FROM ai_txn GROUP BY month) "
    "SELECT * FROM m ORDER BY s DESC LIMIT 3",
    "SELECT t.month, b.limit_paise FROM ai_txn t JOIN ai_budget b ON b.month = t.month",
    "SELECT category, RANK() OVER (ORDER BY SUM(signed_paise) DESC) FROM ai_txn GROUP BY category",
    "SELECT to_char(date::date, 'YYYY-MM') AS mo, COUNT(*) FROM ai_txn GROUP BY 1",
    "SELECT * FROM ai_txn WHERE type = 'expense' AND (month = '2026-09' OR NOT direction = 'credit')"
    " AND signed_paise BETWEEN 1 AND 100 AND category IN ('A', 'B') AND parent_category IS NULL"
    " AND merchant || 'x' LIKE '%x' AND signed_paise % 2 = 0 AND -signed_paise < 0",
]

ATTACKS = [
    "SELECT 1; SELECT 2",
    "DELETE FROM ai_txn",
    "UPDATE ai_txn SET merchant = 'x'",
    "INSERT INTO ai_txn VALUES (1)",
    "DROP TABLE ai_txn",
    "CREATE TABLE x AS SELECT * FROM ai_txn",
    "SELECT * FROM txn",
    "SELECT * FROM public.ai_txn",
    "SELECT * FROM finboard.public.ai_txn",
    "SELECT * FROM pg_catalog.pg_user",
    "SELECT * FROM ai_txn, (SELECT * FROM app_user) u",
    "SELECT * FROM ai_txn WHERE EXISTS (SELECT 1 FROM category)",
    "SELECT set_config('app.user_id', 'someone', false)",
    "SELECT set_config('role', 'finboard_app', false)",
    "SELECT current_setting('app.user_id')",
    "SELECT pg_sleep(10)",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT query_to_xml('select 1', true, true, '')",
    "SELECT dblink('host=evil', 'select 1')",
    "SELECT load_extension('x')",
    "SELECT randomblob(1000000000)",
    "SELECT * FROM generate_series(1, 1000000000)",
    "SELECT * FROM read_csv('/etc/passwd')",
    "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT * FROM r",
    "SELECT 1 -- ; DROP TABLE ai_txn",
    "SELECT /* hidden */ 1",
    "ATTACH DATABASE '/tmp/x.db' AS x",
    "PRAGMA query_only = OFF",
    "SELECT * INTO copy FROM ai_txn",
    "COPY ai_txn TO '/tmp/out'",
    "SET statement_timeout = 0",
    "SELECT date - interval '1 month' FROM ai_txn",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM ai_txn WHERE month = $1",
    "",
    "   ",
    "SELECT " + "1," * 3000 + "1",
]


@pytest.mark.parametrize("sql", ALLOWED)
def test_guard_allows_ordinary_questions(sql: str) -> None:
    guarded = guard(sql)
    assert guarded.sqlite and guarded.postgres


@pytest.mark.parametrize("sql", ATTACKS)
def test_guard_rejects_attacks(sql: str) -> None:
    with pytest.raises(GuardRejected):
        guard(sql)


_TOKENS = st.sampled_from(
    [
        "SELECT", "*", "FROM", "ai_txn", "ai_budget", "txn", "app_user", "WHERE", "1", "=",
        ",", "(", ")", ";", "UNION", "ALL", "pg_sleep(1)", "set_config('a','b',false)",
        "COUNT(*)", "merchant", "'x'", "--", "/*", "*/", "WITH", "RECURSIVE", "r", "AS",
        "ATTACH", "PRAGMA", "DELETE", "INTO", "JOIN", "ON", "LIMIT", "sqlite_master",
        "public.ai_txn", "load_extension('x')", "\"ai_txn\"", "ORDER BY", "GROUP BY",
    ]
)  # fmt: skip


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(_TOKENS, min_size=1, max_size=14).map(" ".join))
def test_guard_output_only_reads_the_two_tables(sql: str) -> None:
    """Whatever the guard accepts runs, and only touches ai_txn / ai_budget."""
    try:
        guarded = guard(sql)
    except GuardRejected:
        return
    parsed = sqlglot.parse_one(guarded.sqlite, read="sqlite")
    ctes = {c.alias_or_name.lower() for c in parsed.find_all(sqlglot.exp.CTE)}
    assert {t.name.lower() for t in parsed.find_all(sqlglot.exp.Table)} <= TABLES | ctes
    functions = {f.sql_name().lower() for f in parsed.find_all(sqlglot.exp.Func)}
    assert not functions & {"pg_sleep", "set_config", "load_extension"}
    with contextlib.suppress(SandboxError):  # a broken query fails safely
        sandbox.run(SandboxRows([], []), guarded.sqlite, timeout=0.5)


# ---------------------------------------------------------------- the sandbox itself

ROWS = SandboxRows(
    txns=[
        ("2026-09-01", "2026-09", "Account A", "savings", "Groceries", None, "expense", "debit",
         Decimal("100.10"), "BIGBASKET"),
        ("2026-09-02", "2026-09", "Account A", "savings", "Groceries", None, "expense", "debit",
         Decimal("0.20"), "BIGBASKET"),
    ],
    budgets=[("2026-09", "Groceries", Decimal("5000.00"))],
)  # fmt: skip


def test_money_is_exact_paise() -> None:
    result = sandbox.run(ROWS, "SELECT SUM(signed_paise) AS total_paise FROM ai_txn")
    assert result.rows == [(Decimal("100.30"),)]
    assert result.columns[0].name == "total" and result.columns[0].kind == "money"


@pytest.mark.parametrize(
    "sql",
    [
        "ATTACH DATABASE ':memory:' AS other",
        "PRAGMA query_only = OFF",
        "PRAGMA table_info(ai_txn)",
        "DELETE FROM ai_txn",
        "INSERT INTO ai_txn SELECT * FROM ai_txn",
        "CREATE TABLE z (a)",
        "DROP TABLE ai_txn",
        "SELECT load_extension('evil')",
        "SELECT randomblob(10)",
        "SELECT sqlite_version()",
        "SELECT * FROM sqlite_master",
        "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT COUNT(*) FROM r",
    ],
)
def test_sandbox_denies_outside_the_allow_list(sql: str) -> None:
    """Even unguarded SQL can't do anything but read the two tables."""
    with pytest.raises(SandboxError):
        sandbox.run(ROWS, sql)


def test_timeout() -> None:
    joins = ", ".join(f"ai_txn t{i}" for i in range(24))
    with pytest.raises(SandboxError, match="took longer"):
        sandbox.run(ROWS, f"SELECT COUNT(*) FROM {joins}", timeout=0.3)


def test_row_cap() -> None:
    many = SandboxRows([ROWS.txns[0]] * 1500, [])
    result = sandbox.run(many, "SELECT merchant FROM ai_txn")
    assert len(result.rows) == 1000 and result.truncated


def test_error_hints_never_quote_data() -> None:
    """SQLite's message is matched, never forwarded: a name that isn't in the model's own SQL
    (it could be a data value) is dropped."""
    own = "SELECT nosuch FROM ai_txn"
    assert describe(sqlite3.OperationalError("no such column: nosuch"), own) == (
        "unknown column nosuch"
    )
    leaked = describe(sqlite3.OperationalError("no such column: CANARY_VALUE"), own)
    assert "CANARY" not in leaked and leaked == "unknown column"
    odd = describe(sqlite3.OperationalError("weird failure quoting 'CANARY 7777.77'"), own)
    assert "CANARY" not in odd and "7777" not in odd


def test_only_tables_from_the_catalog() -> None:
    from finboard.ai.catalog import load

    assert set(load().tables) == TABLES
    assert set(load().columns("ai_txn")) == set(sandbox.TXN_COLUMNS)
    assert set(load().columns("ai_budget")) == set(sandbox.BUDGET_COLUMNS)
