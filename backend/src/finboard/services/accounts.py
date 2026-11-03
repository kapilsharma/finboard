import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from finboard.db.models import Account
from finboard.db.uow import UnitOfWork
from finboard.domain.enums import AccountType
from finboard.domain.errors import Conflict, NotFound

_UPDATABLE = frozenset(
    {"name", "institution", "type", "masked_number", "parser_id", "active", "colour"}
)


class AccountService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def list(self) -> Sequence[Account]:
        return await self.uow.accounts.list()

    async def get(self, account_id: uuid.UUID) -> Account:
        account = await self.uow.accounts.get(account_id)
        if account is None:
            raise NotFound("Account not found")
        return account

    async def create(
        self,
        *,
        name: str,
        type: AccountType,
        institution: str | None = None,
        masked_number: str | None = None,
        parser_id: str | None = None,
        active: bool = True,
        colour: str | None = None,
    ) -> Account:
        await self._ensure_name_free(name)
        account = await self.uow.accounts.add(
            Account(
                name=name,
                type=type,
                institution=institution,
                masked_number=masked_number,
                parser_id=parser_id,
                active=active,
                colour=colour,
            )
        )
        await self.uow.commit()
        return account

    async def update(self, account_id: uuid.UUID, changes: Mapping[str, Any]) -> Account:
        account = await self.get(account_id)
        unknown = set(changes) - _UPDATABLE
        if unknown:
            raise ValueError(f"not updatable: {sorted(unknown)}")
        if "name" in changes and changes["name"].lower() != account.name.lower():
            await self._ensure_name_free(changes["name"], exclude_id=account.id)
        for field, value in changes.items():
            setattr(account, field, value)
        await self.uow.session.flush()
        await self.uow.commit()
        return account

    async def delete(self, account_id: uuid.UUID) -> None:
        # From M2: refuse when the account has transactions (archive it instead).
        account = await self.get(account_id)
        await self.uow.accounts.delete(account)
        await self.uow.commit()

    async def _ensure_name_free(self, name: str, *, exclude_id: uuid.UUID | None = None) -> None:
        if await self.uow.accounts.name_taken(name, exclude_id=exclude_id):
            raise Conflict(f"An account called '{name}' already exists")
