"""The SQLite sandbox, the only place model-written SQL runs (ADR-0032 §2, option G).

A fresh in-memory database per request, loaded with the caller's rows only: other users'
data isn't in it at all, so no SQL can reach it. Inside the engine:

- `set_authorizer` allows reads of the two tables and allow-listed functions only, and denies
  everything else (ATTACH, PRAGMA, writes, schema changes, recursive CTEs);
- `PRAGMA query_only = ON`; extension loading is never enabled;
- a progress handler aborts after 3 s; at most 1,000 rows are fetched.

Money is stored as integer paise, so sums are exact; results convert back to `Decimal`.
Errors come back as `SandboxError` with a locally written description (an error class plus
identifiers that appear in the model's own SQL), never SQLite's own text, which could quote a
data value.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from finboard.ai.allowlist import SQLITE_FUNCTIONS
from finboard.ai.results import Result, from_paise

TIMEOUT_SECONDS = 3.0
MAX_ROWS = 1000
TXN_COLUMNS = (
    "date", "month", "account", "account_type", "category", "parent_category", "type",
    "direction", "signed_paise", "merchant",
)  # fmt: skip
BUDGET_COLUMNS = ("month", "category", "limit_paise")
_SCHEMA = """
CREATE TABLE ai_txn (
    date TEXT NOT NULL, month TEXT NOT NULL, account TEXT NOT NULL, account_type TEXT NOT NULL,
    category TEXT NOT NULL, parent_category TEXT, type TEXT NOT NULL, direction TEXT NOT NULL,
    signed_paise INTEGER NOT NULL, merchant TEXT NOT NULL
);
CREATE TABLE ai_budget (month TEXT NOT NULL, category TEXT NOT NULL, limit_paise INTEGER NOT NULL);
"""
_READABLE = {"ai_txn", "ai_budget"}


@dataclass(frozen=True, slots=True)
class SandboxRows:
    """The caller's rows from the `ai_txn` and `ai_budget` views (read under RLS)."""

    txns: Sequence[tuple[Any, ...]]  # TXN_COLUMNS, with signed_amount as Decimal rupees
    budgets: Sequence[tuple[Any, ...]]  # month, category, monthly_limit (Decimal)


class SandboxError(Exception):
    def __init__(self, hint: str) -> None:
        super().__init__(hint)
        self.hint = hint  # safe for a retry prompt


def to_paise(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value())


def _authorizer(action: int, arg1: str | None, arg2: str | None, *_: object) -> int:
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if (arg1 or "").lower() in _READABLE else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        return (
            sqlite3.SQLITE_OK if (arg2 or "").lower() in SQLITE_FUNCTIONS else sqlite3.SQLITE_DENY
        )
    return sqlite3.SQLITE_DENY  # ATTACH, PRAGMA, INSERT/UPDATE/DELETE, CREATE, RECURSIVE, ...


def _load(conn: sqlite3.Connection, rows: SandboxRows) -> None:
    conn.executescript(_SCHEMA)
    conn.executemany(
        "INSERT INTO ai_txn VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            (str(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7], to_paise(r[8]), r[9])
            for r in rows.txns
        ),
    )
    conn.executemany(
        "INSERT INTO ai_budget VALUES (?, ?, ?)",
        ((m, c, to_paise(limit)) for m, c, limit in rows.budgets),
    )
    conn.commit()


def run(
    rows: SandboxRows,
    sql: str,
    *,
    timeout: float = TIMEOUT_SECONDS,
    max_rows: int = MAX_ROWS,
) -> Result:
    """Load the rows, run one guarded SQLite query, discard everything. Blocking: call it in
    a worker thread."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    try:
        _load(conn, rows)
        conn.execute("PRAGMA query_only = ON")
        conn.execute("PRAGMA trusted_schema = OFF")
        deadline = time.monotonic() + timeout
        conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 2_000)
        conn.set_authorizer(_authorizer)
        try:
            cursor = conn.execute(sql)
            fetched = cursor.fetchmany(max_rows + 1)
        except sqlite3.Error as exc:
            raise SandboxError(describe(exc, sql, timed_out=time.monotonic() > deadline)) from None
        columns = [d[0] for d in cursor.description or ()]
    finally:
        conn.close()
    truncated = len(fetched) > max_rows
    result = from_paise(columns, [tuple(r) for r in fetched[:max_rows]])
    return Result(result.columns, result.rows, truncated)


_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    # (SQLite message shape, hint naming the model's identifier, hint without it)
    (re.compile(r"no such column: ([\w.]+)"), "unknown column {0}", "unknown column"),
    (re.compile(r"no such table: ([\w.]+)"), "unknown table {0}", "unknown table"),
    (re.compile(r"no such function: (\w+)"), "function {0} is not available", "unknown function"),
    (re.compile(r"ambiguous column name: ([\w.]+)"), "ambiguous column {0}", "ambiguous column"),
    (re.compile(r"not authorized"), "the query used something not allowed", ""),
    (re.compile(r"misuse of aggregate"), "an aggregate is used where it isn't allowed", ""),
    (re.compile(r"syntax error"), "SQLite could not parse the transpiled query", ""),
]


def describe(exc: sqlite3.Error, sql: str, *, timed_out: bool = False) -> str:
    """A retry hint written here: an error class plus identifiers from the model's own SQL.
    SQLite's message is matched against known shapes, never forwarded."""
    if timed_out or "interrupted" in str(exc):
        return f"the query took longer than {TIMEOUT_SECONDS:g} s; simplify it"
    own = set(_IDENT.findall(sql))
    message = str(exc)
    for pattern, named, unnamed in _PATTERNS:
        match = pattern.search(message)
        if match:
            groups = match.groups()
            if all(p in own for g in groups for p in g.split(".")):
                return named.format(*groups)
            return unnamed or named
    return f"the query failed to run ({type(exc).__name__})"
