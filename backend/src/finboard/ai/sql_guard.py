"""The guard for model-written SQL (ADR-0032 §2). Allow-lists, not deny-lists:

- exactly one statement, a SELECT (UNION of SELECTs allowed), no comments;
- tables: `ai_txn`, `ai_budget` and the query's own non-recursive CTEs, unqualified;
- functions: an allow-list (aggregates, a few scalar and date helpers, window ranks);
- then transpiled from Postgres to SQLite, the only place it ever runs.

Rejection reasons are written here and quote only identifiers from the model's own SQL, so
they are safe to send back as a retry hint. This is the first layer; the sandbox's authorizer
enforces the same allow-list inside SQLite, and the sandbox only holds the caller's rows.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

TABLES = frozenset({"ai_txn", "ai_budget"})
MAX_SQL_LENGTH = 4000

# Postgres-dialect function names (sqlglot's sql_name, upper case) the model may use.
ALLOWED_FUNCTIONS = frozenset(
    {
        # aggregates
        "COUNT", "SUM", "AVG", "MIN", "MAX", "GROUP_CONCAT", "STRING_AGG",
        # scalar
        "ABS", "ROUND", "COALESCE", "NULLIF", "LOWER", "UPPER", "LENGTH", "TRIM",
        "SUBSTRING", "CASE", "IF", "CAST", "TRY_CAST", "CONCAT", "GREATEST", "LEAST",
        # dates (rewritten for SQLite below where needed)
        "DATE_TRUNC", "TIMESTAMP_TRUNC", "EXTRACT", "TO_CHAR", "TIME_TO_STR", "STR_TO_TIME",
        "DATE", "CURRENT_DATE",
        # windows
        "ROW_NUMBER", "RANK", "DENSE_RANK", "LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE",
    }
)  # fmt: skip
# The same allow-list as SQLite sees it after transpiling (the sandbox's authorizer).
SQLITE_FUNCTIONS = frozenset(
    {
        "count", "sum", "total", "avg", "min", "max", "group_concat",
        "abs", "round", "coalesce", "ifnull", "nullif", "lower", "upper", "length", "trim",
        "substr", "substring", "iif", "like", "strftime", "date",
        "row_number", "rank", "dense_rank", "lag", "lead", "first_value", "last_value",
        "concat",
    }
)  # fmt: skip
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Command,
    exp.Pragma, exp.Into, exp.Merge, exp.Transaction, exp.Commit, exp.Rollback, exp.Set,
    exp.Use, exp.Copy, exp.Lateral, exp.TableSample, exp.Placeholder, exp.Parameter,
    exp.SessionParameter,
)  # fmt: skip
_TRUNC_UNITS = {"MONTH": "start of month", "YEAR": "start of year", "DAY": None}
_EXTRACT_FORMATS = {"YEAR": "%Y", "MONTH": "%m", "DAY": "%d"}


class GuardRejected(ValueError):
    """Why the SQL can't run. Safe to send back to the model."""


@dataclass(frozen=True, slots=True)
class Guarded:
    postgres: str  # normalised, what a pinned widget stores
    sqlite: str  # what the sandbox runs


def guard(sql: str) -> Guarded:
    if not sql or not sql.strip():
        raise GuardRejected("the reply had no SQL")
    if len(sql) > MAX_SQL_LENGTH:
        raise GuardRejected(f"the SQL is longer than {MAX_SQL_LENGTH} characters")
    try:
        tokens = sqlglot.tokenize(sql, read="postgres")
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except (ParseError, TokenError):
        raise GuardRejected("the SQL could not be parsed as PostgreSQL") from None
    if any(t.comments for t in tokens) or "--" in sql or "/*" in sql:
        raise GuardRejected("comments are not allowed")
    if len(statements) != 1:
        raise GuardRejected("write exactly one statement")
    root = statements[0]
    if not isinstance(root, exp.Select | exp.Union):
        raise GuardRejected("only a SELECT is allowed")

    ctes: set[str] = set()
    for with_ in root.find_all(exp.With):
        if with_.args.get("recursive"):
            raise GuardRejected("WITH RECURSIVE is not allowed")
        ctes.update(cte.alias_or_name.lower() for cte in with_.expressions)

    for node in root.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise GuardRejected(f"{type(node).__name__.upper()} is not allowed")
        if isinstance(node, exp.Table):
            _check_table(node, ctes)
        elif isinstance(node, exp.Func):
            name = _function_name(node)
            if name not in ALLOWED_FUNCTIONS:
                raise GuardRejected(f"function {name.lower()} is not allowed")
        elif (
            isinstance(node, exp.Star) and isinstance(node.parent, exp.Column) and node.parent.table
        ):
            continue
        elif isinstance(node, exp.Interval):
            raise GuardRejected(
                "INTERVAL arithmetic is not supported; compare the date or month text"
            )

    postgres = root.sql(dialect="postgres")
    sqlite = _for_sqlite(root.copy()).sql(dialect="sqlite")
    return Guarded(postgres=postgres, sqlite=sqlite)


def _check_table(node: exp.Table, ctes: set[str]) -> None:
    if node.args.get("db") or node.args.get("catalog"):
        raise GuardRejected("qualified table names are not allowed")
    if not isinstance(node.this, exp.Identifier):
        raise GuardRejected("only plain table names are allowed")  # e.g. a table function
    name = node.name.lower()
    if name not in TABLES and name not in ctes:
        raise GuardRejected(f"table {name} is not available; use ai_txn or ai_budget")


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).upper()
    return node.sql_name().upper()


def _for_sqlite(root: exp.Expression) -> exp.Expression:
    """Rewrite the date functions sqlglot leaves in forms SQLite can't run."""

    def rewrite(node: exp.Expression) -> exp.Expression:
        if isinstance(node, exp.DateTrunc | exp.TimestampTrunc):
            unit = node.text("unit").upper() or str(node.args.get("unit", "")).upper()
            unit = unit.strip("'\"")
            if unit not in _TRUNC_UNITS:
                raise GuardRejected(f"date_trunc to {unit.lower() or '?'} is not supported")
            modifier = _TRUNC_UNITS[unit]
            args: list[exp.Expression] = [node.this]
            if modifier:
                args.append(exp.Literal.string(modifier))
            return exp.Anonymous(this="DATE", expressions=args)
        if isinstance(node, exp.Extract):
            unit = node.this.name.upper()
            if unit not in _EXTRACT_FORMATS:
                raise GuardRejected(f"extract({unit.lower()}) is not supported")
            fmt = exp.Anonymous(
                this="STRFTIME",
                expressions=[exp.Literal.string(_EXTRACT_FORMATS[unit]), node.expression],
            )
            return exp.Cast(this=fmt, to=exp.DataType.build("INT"))
        return node

    return root.transform(rewrite)
