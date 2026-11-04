import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from finboard.api.deps import TransferServiceDep
from finboard.api.schemas import (
    AccountRef,
    JobAccepted,
    JobOut,
    TransferList,
    TransferOut,
    TransferSide,
    TxnOut,
)
from finboard.db.models import Account, Txn
from finboard.domain.enums import TransferStatus
from finboard.services.transfers import TransferView

router = APIRouter(prefix="/transfers", tags=["transfers"])


def _side(txn: Txn, account: Account) -> TransferSide:
    return TransferSide(
        transaction=TxnOut.model_validate(txn),
        account=AccountRef(
            id=account.id, name=account.name, type=account.type, masked_number=account.masked_number
        ),
    )


def to_out(view: TransferView) -> TransferOut:
    pair = view.pair
    return TransferOut(
        id=pair.id,
        status=pair.status,
        score=pair.score,
        days_apart=pair.days_apart,
        debit=_side(view.debit, view.debit_account),
        credit=_side(view.credit, view.credit_account),
        created_at=pair.created_at,
        decided_at=pair.decided_at,
    )


@router.get("")
async def list_transfers(
    service: TransferServiceDep,
    status_filter: Annotated[TransferStatus | None, Query(alias="status")] = None,
) -> TransferList:
    return TransferList(items=[to_out(v) for v in await service.list(status_filter)])


@router.post("/suggest", status_code=status.HTTP_202_ACCEPTED)
async def suggest_transfers(service: TransferServiceDep) -> JobAccepted:
    """Look for transfers between your accounts now (also runs after every commit)."""
    return JobAccepted(job=JobOut.model_validate(await service.start_suggest()))


@router.post("/{pair_id}/confirm")
async def confirm_transfer(pair_id: uuid.UUID, service: TransferServiceDep) -> TransferOut:
    """Both sides become Card payment (a credit card is involved) or Own transfer."""
    return to_out(await service.confirm(pair_id))


@router.post("/{pair_id}/reject")
async def reject_transfer(pair_id: uuid.UUID, service: TransferServiceDep) -> TransferOut:
    """Not a transfer: the pair won't be suggested again."""
    return to_out(await service.reject(pair_id))


@router.delete("/{pair_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unpair_transfer(pair_id: uuid.UUID, service: TransferServiceDep) -> None:
    """Undo a pair: the rules categorise both sides again, and it isn't suggested again."""
    await service.unpair(pair_id)
