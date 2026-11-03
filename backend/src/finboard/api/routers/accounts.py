import uuid

from fastapi import APIRouter, status

from finboard.api.deps import AccountServiceDep
from finboard.api.schemas import AccountCreate, AccountList, AccountOut, AccountUpdate

router = APIRouter(prefix="/accounts", tags=["accounts"])


@router.get("")
async def list_accounts(service: AccountServiceDep) -> AccountList:
    return AccountList(items=[AccountOut.model_validate(a) for a in await service.list()])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_account(body: AccountCreate, service: AccountServiceDep) -> AccountOut:
    return AccountOut.model_validate(await service.create(**body.model_dump()))


@router.get("/{account_id}")
async def get_account(account_id: uuid.UUID, service: AccountServiceDep) -> AccountOut:
    return AccountOut.model_validate(await service.get(account_id))


@router.patch("/{account_id}")
async def update_account(
    account_id: uuid.UUID, body: AccountUpdate, service: AccountServiceDep
) -> AccountOut:
    return AccountOut.model_validate(await service.update(account_id, body.changes()))


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(account_id: uuid.UUID, service: AccountServiceDep) -> None:
    await service.delete(account_id)
