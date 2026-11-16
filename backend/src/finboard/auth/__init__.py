"""Authentication seam (ADR-0021). Routes and services only ever see a `Principal`.

`LocalSingleUserBackend` is local mode (one user, no login). Server mode uses
`finboard.auth.sessions.SessionBackend` (ADR-0041).
"""

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
    async def authenticate(
        self, headers: Mapping[str, str], method: str = "GET"
    ) -> Principal | None:
        """Return who is making the request, or None if nobody is signed in.

        `method` is the HTTP method: a backend may ask more of a request that changes
        something (the session backend wants its CSRF token).
        """
        ...


class LocalSingleUserBackend:
    """Local mode (`FINBOARD_MODE=local`): every request is the single local user."""

    def __init__(self, principal: Principal) -> None:
        self._principal = principal

    async def authenticate(
        self, headers: Mapping[str, str], method: str = "GET"
    ) -> Principal | None:
        return self._principal
