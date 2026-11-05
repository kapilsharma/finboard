"""Ask Finboard (M4a, ADR-0032). Every route is a 404 (`ai_off`) unless the operator made
Ask available and you turned it on in Settings > AI."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, status

from finboard.api.deps import AskServiceDep
from finboard.api.schemas import (
    AskHistoryOut,
    AskIn,
    AskOut,
    AskQueryOut,
    AskResultOut,
    Cell,
    ChartOut,
    PinIn,
    ResultColumnOut,
    WidgetListOut,
    WidgetOut,
)
from finboard.db.models import AskQuery

router = APIRouter(tags=["ask"])


def _cell(value: Any) -> Cell:
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, str | int | float):
        return value
    return str(value)


def _result(result: Any) -> AskResultOut | None:
    if result is None:
        return None
    return AskResultOut(
        columns=[ResultColumnOut(name=c.name, kind=c.kind) for c in result.columns],
        rows=[[_cell(v) for v in row] for row in result.rows],
        truncated=result.truncated,
    )


def _query(q: AskQuery, *, pinned: bool = False) -> AskQueryOut:
    return AskQueryOut(
        id=q.id,
        question=q.question,
        status=q.status,
        path=q.path,
        spec=q.spec,
        sql=q.sql,
        chart=ChartOut(**q.chart) if q.chart else None,
        clarification=q.clarification,
        error=q.error,
        retries=q.retries,
        latency_ms=q.latency_ms,
        model=q.model,
        tokens_in=q.tokens_in,
        tokens_out=q.tokens_out,
        created_at=q.created_at,
        pinned=pinned,
    )


@router.post("/ask")
async def ask(body: AskIn, service: AskServiceDep) -> AskOut:
    """Answer a question as a chart or table. Only the question, the catalog, your category
    paths and account aliases go to the provider; never rows, amounts or descriptions."""
    outcome = await service.ask(body.question)
    return AskOut(
        query=_query(outcome.query), answer=outcome.answer, result=_result(outcome.result)
    )


@router.get("/ask/history")
async def ask_history(service: AskServiceDep) -> AskHistoryOut:
    """Your last 50 questions (results are never stored)."""
    pinned = {w.ask_query_id for w, _ in await service.uow.ask.widgets()}
    return AskHistoryOut(items=[_query(q, pinned=q.id in pinned) for q in await service.history()])


@router.delete("/ask/history", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ask_history(service: AskServiceDep) -> None:
    """Forget every question that isn't pinned to the dashboard."""
    await service.delete_history()


@router.post("/ask/{query_id}/pin", status_code=status.HTTP_201_CREATED)
async def pin_question(query_id: uuid.UUID, body: PinIn, service: AskServiceDep) -> WidgetOut:
    """Pin an answered question to the dashboard. It re-runs locally, with no AI call."""
    widget = await service.pin(query_id, body.title)
    view = next(v for v in await service.widgets() if v.widget.id == widget.id)
    return _widget(view)


def _widget(v: Any) -> WidgetOut:
    return WidgetOut(
        id=v.widget.id,
        title=v.widget.title,
        sort_order=v.widget.sort_order,
        status=v.status,
        message=v.message,
        query=_query(v.query, pinned=True),
        chart=ChartOut(**v.chart) if v.chart else None,
        result=_result(v.result),
    )


@router.get("/dashboard/widgets")
async def dashboard_widgets(service: AskServiceDep) -> WidgetListOut:
    """Pinned questions, re-run now on your own data."""
    return WidgetListOut(items=[_widget(v) for v in await service.widgets()])


@router.delete("/dashboard/widgets/{widget_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard_widget(widget_id: uuid.UUID, service: AskServiceDep) -> None:
    await service.delete_widget(widget_id)
