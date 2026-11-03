from typing import Any

from finboard.db.uow import UnitOfWork
from finboard.domain.enums import Theme

# Known preference keys and their defaults. Unknown stored keys are ignored on read.
DEFAULTS: dict[str, Any] = {"theme": Theme.SYSTEM.value}


class SettingsService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def get(self) -> dict[str, Any]:
        stored = await self.uow.settings.all()
        return {key: stored.get(key, default) for key, default in DEFAULTS.items()}

    async def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        for key, value in changes.items():
            if key not in DEFAULTS:
                raise ValueError(f"unknown setting: {key}")
            await self.uow.settings.set(key, value)
        await self.uow.commit()
        return await self.get()
