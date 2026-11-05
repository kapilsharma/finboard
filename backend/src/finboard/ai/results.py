"""Query results, kept out of the graph state (ADR-0030 §4, ADR-0032 §3).

Execute nodes put rows in a per-request `ResultStore`; the graph carries only the result id
and a `Shape` (column names and kinds, row count). The chart is chosen from the shape, with
the model's hint as a tie-breaker, and the answer sentence is filled in locally.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

Kind = Literal["text", "month", "date", "money", "count", "number"]
ChartKind = Literal["bar", "grouped_bar", "line", "table"]
PAISE_SUFFIX = "_paise"
_CENT = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    kind: Kind


@dataclass(frozen=True, slots=True)
class Result:
    columns: list[Column]
    rows: list[tuple[Any, ...]]
    truncated: bool = False

    def shape(self) -> Shape:
        return Shape([(c.name, c.kind) for c in self.columns], len(self.rows), self.truncated)


@dataclass(frozen=True, slots=True)
class Shape:
    """All the graph may know about a result."""

    columns: list[tuple[str, str]]
    row_count: int
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "columns": [list(c) for c in self.columns],
            "row_count": self.row_count,
            "truncated": self.truncated,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Shape:
        return cls(
            [(str(a), str(b)) for a, b in raw["columns"]], raw["row_count"], raw["truncated"]
        )


@dataclass
class ResultStore:
    """Per request; dropped with it."""

    _results: dict[str, Result] = field(default_factory=dict)

    def put(self, result: Result) -> str:
        key = uuid.uuid4().hex
        self._results[key] = result
        return key

    def get(self, key: str) -> Result:
        return self._results[key]


@dataclass(frozen=True, slots=True)
class Chart:
    kind: ChartKind
    x: str | None = None
    series: str | None = None
    y: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "x": self.x, "series": self.series, "y": self.y}


_DIMENSIONS = {"text", "month", "date"}
_MEASURES = {"money", "count", "number"}


def choose_chart(shape: Shape, hint: str | None = None) -> Chart:
    dims = [n for n, k in shape.columns if k in _DIMENSIONS]
    measures = [n for n, k in shape.columns if k in _MEASURES]
    kinds = dict(shape.columns)
    if shape.row_count == 0 or len(measures) != 1 or len(dims) + 1 != len(shape.columns):
        return Chart("table")
    y = measures[0]
    if len(dims) == 1 and shape.row_count <= 60:
        x = dims[0]
        timeline = kinds[x] in {"month", "date"}
        if hint == "table":
            return Chart("table", x, None, y)
        if timeline and hint != "bar":
            return Chart("line" if hint == "line" or shape.row_count > 12 else "bar", x, None, y)
        return Chart("bar", x, None, y)
    if len(dims) == 2 and shape.row_count <= 200 and hint != "table":
        a, b = dims
        x, series = (b, a) if kinds[b] in {"month", "date"} and kinds[a] == "text" else (a, b)
        return Chart("line" if hint == "line" else "grouped_bar", x, series, y)
    return Chart("table", dims[0] if dims else None, None, y)


def paise_to_rupees(value: Any) -> Decimal | None:
    if value is None:
        return None
    return (Decimal(int(value)) / 100).quantize(_CENT, ROUND_HALF_UP)


def from_paise(columns: list[str], rows: list[tuple[Any, ...]]) -> Result:
    """Sandbox output: `*_paise` columns become money in rupees (Decimal), other numbers stay."""
    money = [c.endswith(PAISE_SUFFIX) for c in columns]
    cols = []
    for i, name in enumerate(columns):
        if money[i]:
            cols.append(Column(name[: -len(PAISE_SUFFIX)] or name, "money"))
        else:
            sample = next((r[i] for r in rows if r[i] is not None), None)
            kind: Kind = "number" if isinstance(sample, int | float) else "text"
            if kind == "text" and isinstance(sample, str) and _looks_like_month(sample):
                kind = "month"
            cols.append(Column(name, kind))
    converted = [
        tuple(
            paise_to_rupees(v) if money[i] else (Decimal(str(v)) if isinstance(v, float) else v)
            for i, v in enumerate(row)
        )
        for row in rows
    ]
    return Result(cols, converted)


def _looks_like_month(text: str) -> bool:
    return len(text) == 7 and text[4] == "-" and text[:4].isdigit() and text[5:].isdigit()


# ---------------------------------------------------------------- the answer (local templates)


def inr(value: Decimal) -> str:
    """₹1,42,702.04 (Indian digit grouping), the same as the UI's format.ts."""
    sign = "\u2212" if value < 0 else ""  # a real minus sign, as the UI shows
    whole, _, frac = f"{abs(value):.2f}".partition(".")
    head, tail = whole[:-3], whole[-3:]
    groups: list[str] = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    grouped = ",".join([*groups, tail]) if groups else tail
    return f"{sign}₹{grouped}.{frac}"


def answer(result: Result, title: str) -> str:
    n = len(result.rows)
    if n == 0:
        return f"{title}: no matching transactions."
    money = [i for i, c in enumerate(result.columns) if c.kind == "money"]
    dims = [c for c in result.columns if c.kind in _DIMENSIONS]
    if not dims and n == 1 and len(result.columns) == 1:
        value = result.rows[0][0]
        return f"{title}: {inr(value) if money else value}."
    if len(money) == 1:
        total = sum((r[money[0]] or Decimal(0) for r in result.rows), Decimal(0))
        more = " (first 1,000 rows)" if result.truncated else ""
        return f"{title}: {inr(total)} in total across {n} rows{more}."
    return f"{title}: {n} rows."
