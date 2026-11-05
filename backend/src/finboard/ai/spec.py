"""Ask Finboard's spec path (ADR-0032 §1): the model fills a `QuerySpec`, and this module
turns it into SQL deterministically, on the same metric definitions as the dashboard
(ARCHITECTURE §12: signed sums per category type, transfers never counted). The model never
writes this SQL. It runs in Postgres against the `ai_txn` view, as the app role under RLS.

Pure: returns SQL text and bind parameters; the service executes them.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from finboard.ai.results import Column

Metric = Literal["spending", "income", "invested", "net", "count"]
GroupBy = Literal["month", "category", "account", "merchant"]
ChartKind = Literal["bar", "grouped_bar", "line", "table"]


class QuerySpec(BaseModel):
    """What to compute. Every field is a name the prompt listed, never a data value."""

    model_config = ConfigDict(extra="forbid")

    metric: Metric = "spending"
    categories: list[str] = Field(default_factory=list, max_length=20)
    accounts: list[str] = Field(default_factory=list, max_length=10)
    merchant: str | None = Field(default=None, max_length=60)
    start: date | None = None
    end: date | None = None
    last_months: int | None = Field(default=None, ge=1, le=60)
    group_by: list[GroupBy] = Field(default_factory=list, max_length=2)
    top: int | None = Field(default=None, ge=1, le=50)
    chart: ChartKind | None = None

    @field_validator("group_by")
    @classmethod
    def _distinct(cls, value: list[GroupBy]) -> list[GroupBy]:
        if len(set(value)) != len(value):
            raise ValueError("group_by repeats a field")
        return value


class SpecError(ValueError):
    """The spec names something that doesn't exist. The message only repeats names the model
    itself sent, so it is safe to use as a retry hint."""


@dataclass(frozen=True, slots=True)
class CategoryPath:
    name: str
    parent: str | None = None

    @property
    def path(self) -> str:
        return f"{self.parent} > {self.name}" if self.parent else self.name


@dataclass(frozen=True, slots=True)
class BuiltQuery:
    sql: str
    params: dict[str, Any]
    columns: list[Column]
    metric: Metric
    start: date | None = None
    end: date | None = None
    filters: list[str] = field(default_factory=list)


_METRIC_TYPES: dict[Metric, tuple[str, ...]] = {
    "spending": ("expense",),
    "income": ("income",),
    "invested": ("investment",),
    "net": ("income", "expense"),
    "count": ("income", "expense", "investment"),
}
_METRIC_VALUE: dict[Metric, str] = {
    "spending": "COALESCE(SUM(signed_amount), 0)",
    "income": "COALESCE(SUM(signed_amount), 0)",
    "invested": "COALESCE(SUM(signed_amount), 0)",
    "net": "COALESCE(SUM(CASE WHEN type = 'income' THEN signed_amount ELSE -signed_amount END), 0)",
    "count": "COUNT(*)",
}


def month_start(d: date, months_back: int = 0) -> date:
    index = d.year * 12 + d.month - 1 - months_back
    return date(index // 12, index % 12 + 1, 1)


def resolve_range(spec: QuerySpec, today: date) -> tuple[date | None, date | None]:
    """`last_months=6` means this month and the five before it, so a pinned widget rolls."""
    if spec.last_months:
        return month_start(today, spec.last_months - 1), today
    return spec.start, spec.end


def _match_category(wanted: str, known: Sequence[CategoryPath]) -> CategoryPath:
    key = " ".join(wanted.replace(">", " > ").split()).casefold()
    for c in known:
        if key in (c.path.casefold(), " ".join(c.path.replace(">", " > ").split()).casefold()):
            return c
    matches = [c for c in known if c.name.casefold() == key]
    if len(matches) == 1:
        return matches[0]
    raise SpecError(f"unknown category {wanted!r}: use one of the listed category paths")


def build(
    spec: QuerySpec,
    *,
    today: date,
    categories: Sequence[CategoryPath],
    accounts: Sequence[str],
) -> BuiltQuery:
    start, end = resolve_range(spec, today)
    if start and end and start > end:
        raise SpecError("start is after end")
    params: dict[str, Any] = {"types": list(_METRIC_TYPES[spec.metric])}
    where = ["type = ANY(:types)"]
    filters: list[str] = []

    if spec.categories:
        ors = []
        for i, wanted in enumerate(spec.categories):
            c = _match_category(wanted, categories)
            params[f"c{i}"] = c.name
            filters.append(c.path)
            if c.parent is None:  # a top-level category includes its children
                ors.append(f"(category = :c{i} OR parent_category = :c{i})")
            else:
                params[f"p{i}"] = c.parent
                ors.append(f"(category = :c{i} AND parent_category = :p{i})")
        where.append("(" + " OR ".join(ors) + ")")
    if spec.accounts:
        known = {a.casefold(): a for a in accounts}
        chosen = []
        for wanted in spec.accounts:
            if wanted.casefold() not in known:
                raise SpecError(f"unknown account {wanted!r}: use one of the listed aliases")
            chosen.append(known[wanted.casefold()])
        params["accounts"] = chosen
        where.append("account = ANY(:accounts)")
        filters.extend(chosen)
    if spec.merchant:
        params["merchant"] = "%" + _escape_like(spec.merchant.strip().upper()) + "%"
        where.append("merchant LIKE :merchant ESCAPE '\\'")
    if start:
        params["start"] = start
        where.append("date >= :start")
    if end:
        params["end"] = end
        where.append("date <= :end")

    groups = list(spec.group_by)
    value = _METRIC_VALUE[spec.metric]
    select = [*groups, f"{value} AS {spec.metric}"]
    # Every fragment is a constant from this module; values go in as bind parameters.
    sql = f"SELECT {', '.join(select)} FROM ai_txn WHERE {' AND '.join(where)}"  # noqa: S608
    if groups:
        sql += f" GROUP BY {', '.join(groups)}"
        if "month" in groups:
            order = ["month", *(g for g in groups if g != "month")]
        else:
            order = [f"{spec.metric} DESC", *groups]
        sql += f" ORDER BY {', '.join(order)}"
    if spec.top:
        sql += f" LIMIT {int(spec.top)}"
    columns = [Column(g, "month" if g == "month" else "text") for g in groups]
    columns.append(Column(spec.metric, "count" if spec.metric == "count" else "money"))
    return BuiltQuery(sql, params, columns, spec.metric, start, end, filters)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
