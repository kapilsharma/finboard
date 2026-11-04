"""Transfers between the user's own accounts (ARCHITECTURE §9, "Transfer pairing").

`transfers.suggest` (a job, queued after every commit) proposes pairs; the user confirms or
rejects each one (OQ-6: never confirmed automatically). Confirming puts both sides in *Card
payment* (if one side is a credit card) or *Own transfer*, with `categorised_by=transfer`, which
re-apply never overwrites. Undoing a pair rejects it (so it isn't suggested again) and lets the
rules categorise both sides again.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from finboard.categorisation.matcher import TxnFacts
from finboard.categorisation.pairing import PairCandidate, suggest_pairs, transfer_category_key
from finboard.db.models import Account, Job, TransferPair, Txn
from finboard.db.uow import UnitOfWork
from finboard.domain.enums import CategorisedBy, TransferStatus
from finboard.domain.errors import Conflict, NotFound
from finboard.services.categoriser import Categoriser
from finboard.services.jobs import JobQueue, JobService

log = structlog.get_logger(__name__)

SUGGEST_TASK = "transfers.suggest"


@dataclass
class TransferView:
    pair: TransferPair
    debit: Txn
    credit: Txn
    debit_account: Account
    credit_account: Account


def _now() -> datetime:
    return datetime.now(UTC)


class TransferService:
    def __init__(self, uow: UnitOfWork, queue: JobQueue) -> None:
        self.uow = uow
        self.jobs = JobService(uow, queue)

    async def list(self, status: TransferStatus | None) -> list[TransferView]:
        pairs = await self.uow.transfers.list(status)
        txns = {
            t.id: t
            for t in await self.uow.txns.get_many(
                [i for p in pairs for i in (p.debit_txn_id, p.credit_txn_id)]
            )
        }
        accounts = {a.id: a for a in await self.uow.accounts.list()}
        views = []
        for pair in pairs:
            debit, credit = txns[pair.debit_txn_id], txns[pair.credit_txn_id]
            views.append(
                TransferView(
                    pair, debit, credit, accounts[debit.account_id], accounts[credit.account_id]
                )
            )
        return views

    async def view(self, pair_id: uuid.UUID) -> TransferView:
        for view in await self.list(None):
            if view.pair.id == pair_id:
                return view
        raise NotFound("Transfer not found")

    async def start_suggest(self) -> Job:
        return await self.jobs.submit(SUGGEST_TASK)

    async def run_suggest(self, _job: Job) -> dict[str, Any]:
        """Worker side: pair up unpaired transactions that transfers haven't claimed yet."""
        rows = await self.uow.txns.facts(exclude_paired=True)
        candidates = [
            PairCandidate(
                id=row.id,
                account_id=row.account_id,
                account_type=row.account_type.value,
                date=row.date,
                direction=row.direction.value,
                amount=row.amount,
                description_norm=row.description_norm,
            )
            for row in rows
            if row.categorised_by is not CategorisedBy.TRANSFER
        ]
        pairs = suggest_pairs(candidates, rejected=await self.uow.transfers.rejected_keys())
        added = await self.uow.transfers.add_suggestions(
            [
                {
                    "debit_txn_id": p.debit_id,
                    "credit_txn_id": p.credit_id,
                    "score": p.score,
                    "days_apart": p.days_apart,
                }
                for p in pairs
            ]
        )
        log.info("transfers.suggested", candidates=len(candidates), suggested=added)
        return {"suggested": added}

    async def confirm(self, pair_id: uuid.UUID) -> TransferView:
        pair = await self._locked(pair_id)
        if pair.status is TransferStatus.CONFIRMED:
            return await self.view(pair.id)
        if pair.status is not TransferStatus.SUGGESTED:
            raise Conflict("Only a suggested transfer can be confirmed")
        debit, credit = await self._sides(pair)
        accounts = {a.id: a for a in await self.uow.accounts.list()}
        key = transfer_category_key(
            [accounts[debit.account_id].type.value, accounts[credit.account_id].type.value]
        )
        category = await self.uow.categories.by_system_key(key)
        if category is None:
            raise Conflict(f"The system category '{key}' is missing")
        for txn in (debit, credit):
            txn.category_id, txn.type = category.id, category.type
            txn.categorised_by, txn.rule_id, txn.needs_review = CategorisedBy.TRANSFER, None, False
        pair.status, pair.decided_at = TransferStatus.CONFIRMED, _now()
        await self.uow.users.bump_data_version(self.uow.user_id)
        await self.uow.session.flush()
        await self.uow.commit()
        return await self.view(pair.id)

    async def reject(self, pair_id: uuid.UUID) -> TransferView:
        pair = await self._locked(pair_id)
        if pair.status is TransferStatus.CONFIRMED:
            raise Conflict("This transfer is confirmed; undo it instead")
        pair.status, pair.decided_at = TransferStatus.REJECTED, _now()
        await self.uow.session.flush()
        await self.uow.commit()
        return await self.view(pair.id)

    async def unpair(self, pair_id: uuid.UUID) -> None:
        """Undo a pair (DELETE /transfers/{id}). It is kept as rejected so it isn't suggested
        again, and the rules categorise both sides afresh."""
        pair = await self._locked(pair_id)
        await self.release(pair)
        await self.uow.commit()

    async def release(self, pair: TransferPair, *, keep: uuid.UUID | None = None) -> None:
        """Reject a pair and recategorise its sides by rules (except `keep`, which the caller
        is about to change itself). The caller commits."""
        was_confirmed = pair.status is TransferStatus.CONFIRMED
        pair.status, pair.decided_at = TransferStatus.REJECTED, _now()
        if was_confirmed:
            categoriser = await Categoriser.load(self.uow)
            accounts = {a.id: a for a in await self.uow.accounts.list()}
            for txn in await self._sides(pair):
                if txn.id == keep or txn.categorised_by is not CategorisedBy.TRANSFER:
                    continue
                decision = categoriser.decide(
                    TxnFacts(txn.description_norm, txn.direction.value, txn.amount, txn.account_id),
                    accounts[txn.account_id].type,
                )
                txn.category_id, txn.type = decision.category_id, decision.type
                txn.categorised_by, txn.rule_id = decision.categorised_by, decision.rule_id
                txn.needs_review = decision.needs_review
            await categoriser.record_timeouts(self.uow)
            await self.uow.users.bump_data_version(self.uow.user_id)
        await self.uow.session.flush()

    async def _sides(self, pair: TransferPair) -> Sequence[Txn]:
        txns = {
            t.id: t
            for t in await self.uow.txns.get_many(
                [pair.debit_txn_id, pair.credit_txn_id], for_update=True
            )
        }
        return txns[pair.debit_txn_id], txns[pair.credit_txn_id]

    async def _locked(self, pair_id: uuid.UUID) -> TransferPair:
        pair = await self.uow.transfers.get(pair_id, for_update=True)
        if pair is None:
            raise NotFound("Transfer not found")
        return pair
