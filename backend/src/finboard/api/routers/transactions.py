import uuid

from fastapi import APIRouter

from finboard.api.deps import TransactionServiceDep
from finboard.api.schemas import TxnBulkIn, TxnBulkOut, TxnOut, TxnUpdate

router = APIRouter(prefix="/transactions", tags=["transactions"])


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
