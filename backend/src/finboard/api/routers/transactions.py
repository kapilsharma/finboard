import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from finboard.api.deps import TransactionServiceDep
from finboard.api.routers.dashboard import Month
from finboard.api.schemas import (
    TxnBulkIn,
    TxnBulkOut,
    TxnListItem,
    TxnListOut,
    TxnOut,
    TxnSums,
    TxnUpdate,
)
from finboard.domain.enums import CategoryType
from finboard.domain.errors import ValidationFailed
from finboard.services.dashboard import month_end, parse_month

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("")
async def list_transactions(
    service: TransactionServiceDep,
    month: Month = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    account_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    category_id: Annotated[list[uuid.UUID] | None, Query()] = None,
    type_filter: Annotated[list[CategoryType] | None, Query(alias="type")] = None,
    needs_review: bool | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: Literal["date", "description", "account", "category", "type", "amount"] = "date",
    order: Literal["asc", "desc"] = "desc",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query(max_length=500)] = None,
) -> TxnListOut:
    """Transactions in a month (`month`) or a date range (`from`, `to`), filtered and sorted,
    a page at a time: pass `next_cursor` back as `cursor`. `total` and `sums` cover every
    matching row, not just the page."""
    if month and (date_from or date_to):
        raise ValidationFailed("Use either month or from/to, not both")
    start, end = date_from, date_to
    if month:
        start = parse_month(month)
        end = month_end(start)
    page = await service.list(
        start=start,
        end=end,
        account_ids=account_id or (),
        category_ids=category_id or (),
        types=type_filter or (),
        needs_review=needs_review,
        q=q,
        sort=sort,
        descending=order == "desc",
        cursor=cursor,
        limit=limit,
    )
    return TxnListOut(
        items=[
            TxnListItem.model_validate(
                {
                    **TxnOut.model_validate(row.txn).model_dump(),
                    "description_raw": row.txn.description_raw,
                    "account_name": row.account_name,
                    "category_name": row.category_name,
                }
            )
            for row in page.items
        ],
        next_cursor=page.next_cursor,
        total=page.total,
        sums=TxnSums(
            income=page.totals.income,
            spending=page.totals.spending,
            invested=page.totals.invested,
            transfers=page.totals.transfers,
        ),
    )


@router.get("/{txn_id}")
async def get_transaction(txn_id: uuid.UUID, service: TransactionServiceDep) -> TxnOut:
    return TxnOut.model_validate(await service.get(txn_id))


@router.patch("/{txn_id}")
async def update_transaction(
    txn_id: uuid.UUID, body: TxnUpdate, service: TransactionServiceDep
) -> TxnOut:
    """Categorise by hand (`categorised_by=manual`), or set notes and a payee label."""
    return TxnOut.model_validate(await service.update(txn_id, body.changes()))


@router.post("/bulk")
async def bulk_categorise(body: TxnBulkIn, service: TransactionServiceDep) -> TxnBulkOut:
    """Put up to 1000 transactions in one category by hand."""
    return TxnBulkOut(updated=await service.bulk_categorise(body.ids, body.category_id))
