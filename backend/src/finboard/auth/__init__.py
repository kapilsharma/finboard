"""Authentication seam (ADR-0021). Routes and services only ever see a `Principal`."""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: uuid.UUID
    username: str
    display_name: str


class AuthBackend(Protocol):
    async def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        """Return who is making the request, or None if nobody is signed in."""
        ...


class LocalSingleUserBackend:
    """v1 (`FINBOARD_MODE=local`): every request is the single local user."""

    def __init__(self, principal: Principal) -> None:
        self._principal = principal

    async def authenticate(self, headers: Mapping[str, str]) -> Principal | None:
        return self._principal
