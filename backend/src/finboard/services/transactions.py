"""Manual categorisation of committed transactions (PATCH /transactions/{id}, /bulk).

A manual choice sets `categorised_by=manual` and clears `needs_review`; re-apply leaves it
alone unless asked to include manual rows. Changing the category of one side of a confirmed
transfer undoes the pair, so the other side doesn't stay labelled as a transfer on its own.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from finboard.db.models import Category, Txn
from finboard.db.uow import UnitOfWork
from finboard.domain.enums import CategorisedBy
from finboard.domain.errors import NotFound, ValidationFailed
from finboard.services.jobs import JobQueue
from finboard.services.transfers import TransferService

MAX_BULK = 1000
_UPDATABLE = frozenset({"category_id", "notes", "payee_label"})


class TransactionService:
    def __init__(self, uow: UnitOfWork, queue: JobQueue) -> None:
        self.uow = uow
        self.transfers = TransferService(uow, queue)

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
