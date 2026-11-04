"""Manual categorisation of committed transactions (PATCH /transactions/{id}, /bulk).

A manual choice sets `categorised_by=manual` and clears `needs_review`; re-apply leaves it
alone unless asked to include manual rows. Changing the category of one side of a confirmed
transfer undoes the pair, so the other side doesn't stay labelled as a transfer on its own.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from finboard.categorisation.normalise import normalise
from finboard.db.models import Category, Txn
from finboard.db.repos import TxnFilters, TxnListRow
from finboard.db.uow import UnitOfWork
from finboard.domain import metrics
from finboard.domain.enums import CategorisedBy, CategoryType
from finboard.domain.errors import NotFound, ValidationFailed
from finboard.services.jobs import JobQueue
from finboard.services.transfers import TransferService

MAX_BULK = 1000
_UPDATABLE = frozenset({"category_id", "notes", "payee_label"})


MAX_PAGE = 200


@dataclass(frozen=True, slots=True)
class TxnPage:
    items: list[TxnListRow]
    next_cursor: str | None
    total: int
    totals: metrics.Totals


def _encode_cursor(value: Any, txn_id: uuid.UUID) -> str:
    if isinstance(value, date):
        value = value.isoformat()
    elif isinstance(value, Decimal):
        value = str(value)
    elif hasattr(value, "value"):
        value = value.value
    raw = json.dumps([value, str(txn_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str, sort: str) -> tuple[Any, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        value, txn_id = json.loads(raw)
        parsed: Any
        if sort == "date":
            parsed = date.fromisoformat(value)
        elif sort == "amount":
            parsed = Decimal(value)
        elif sort == "type":
            parsed = CategoryType(value)
        else:
            parsed = str(value)
        return parsed, uuid.UUID(txn_id)
    except (ValueError, TypeError, InvalidOperation, binascii.Error, json.JSONDecodeError):
        raise ValidationFailed("Invalid cursor") from None


class TransactionService:
    def __init__(self, uow: UnitOfWork, queue: JobQueue) -> None:
        self.uow = uow
        self.transfers = TransferService(uow, queue)

    async def list(
        self,
        *,
        start: date | None,
        end: date | None,
        account_ids: Sequence[uuid.UUID] = (),
        category_ids: Sequence[uuid.UUID] = (),
        types: Sequence[CategoryType] = (),
        needs_review: bool | None = None,
        q: str | None = None,
        sort: str = "date",
        descending: bool = True,
        cursor: str | None = None,
        limit: int = 50,
    ) -> TxnPage:
        """A page of transactions plus the count and signed totals of everything the filters
        match (ARCHITECTURE §10). A category filter includes its sub-categories."""
        if sort not in self.uow.txns.SORT_KEYS:
            raise ValidationFailed(f"sort must be one of {', '.join(self.uow.txns.SORT_KEYS)}")
        if not 1 <= limit <= MAX_PAGE:
            raise ValidationFailed(f"limit must be between 1 and {MAX_PAGE}")
        if start and end and start > end:
            raise ValidationFailed("from must not be after to")
        if category_ids:
            categories = await self.uow.categories.list()
            wanted = set(category_ids)
            category_ids = [c.id for c in categories if c.id in wanted or c.parent_id in wanted]
            if not category_ids:
                category_ids = list(wanted)  # unknown ids: match nothing rather than everything
        text = (q or "").strip()
        filters = TxnFilters(
            start=start,
            end=end,
            account_ids=account_ids,
            category_ids=category_ids,
            types=types,
            needs_review=needs_review,
            q=text or None,
            q_norm=normalise(text) or None,
        )
        after = _decode_cursor(cursor, sort) if cursor else None
        rows = await self.uow.txns.page(
            filters, sort=sort, descending=descending, after=after, limit=limit + 1
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = _encode_cursor(rows[-1].sort_value, rows[-1].txn.id) if has_more else None
        totals = metrics.Totals()
        total = 0
        for type_, direction, amount, count in await self.uow.txns.filtered_sums(filters):
            totals.add(type_, direction, amount)
            total += count
        return TxnPage(rows, next_cursor, total, totals)

    async def get(self, txn_id: uuid.UUID) -> Txn:
        txn = await self.uow.txns.get(txn_id)
        if txn is None:
            raise NotFound("Transaction not found")
        return txn

    async def update(self, txn_id: uuid.UUID, changes: Mapping[str, Any]) -> Txn:
        unknown = set(changes) - _UPDATABLE
        if unknown:
            raise ValueError(f"not updatable: {sorted(unknown)}")
        txn = await self.uow.txns.get(txn_id, for_update=True)
        if txn is None:
            raise NotFound("Transaction not found")
        if "category_id" in changes:
            category = await self._category(changes["category_id"])
            await self._categorise([txn], category)
        for name in ("notes", "payee_label"):
            if name in changes:
                setattr(txn, name, changes[name])
        await self.uow.users.bump_data_version(self.uow.user_id)
        await self.uow.session.flush()
        await self.uow.commit()
        return txn

    async def bulk_categorise(self, ids: Sequence[uuid.UUID], category_id: uuid.UUID) -> int:
        unique = list(dict.fromkeys(ids))
        if not unique:
            return 0
        if len(unique) > MAX_BULK:
            raise ValidationFailed(f"At most {MAX_BULK} transactions at a time")
        category = await self._category(category_id)
        txns = await self.uow.txns.get_many(unique, for_update=True)
        if len(txns) != len(unique):
            raise NotFound("Transaction not found")
        await self._categorise(txns, category)
        await self.uow.users.bump_data_version(self.uow.user_id)
        await self.uow.session.flush()
        await self.uow.commit()
        return len(txns)

    async def _categorise(self, txns: Sequence[Txn], category: Category) -> None:
        for txn in txns:
            if txn.categorised_by is CategorisedBy.TRANSFER and txn.category_id != category.id:
                pair = await self.uow.transfers.active_for_txn(txn.id)
                if pair is not None:
                    await self.transfers.release(pair, keep=txn.id)
            txn.category_id, txn.type = category.id, category.type
            txn.categorised_by, txn.rule_id, txn.needs_review = CategorisedBy.MANUAL, None, False

    async def _category(self, category_id: uuid.UUID | None) -> Category:
        if category_id is None:
            raise ValidationFailed("Choose a category")
        category = await self.uow.categories.get(category_id)
        if category is None:
            raise ValidationFailed("Unknown category")
        return category
