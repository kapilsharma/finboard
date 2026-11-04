"""Ephemeral statement-password handoff from the API to a worker (ADR-0027).

The password is Fernet-encrypted with a key derived from `FINBOARD_SECRET_KEY` and stored in
Redis at `secret:<ref>` for at most 120 s. The worker takes it with GETDEL, so it can be read
once. Only the opaque `ref` travels in the broker message. Nothing here is ever logged.
"""

import base64
import hashlib
import re
import uuid
from typing import Protocol

from cryptography.fernet import Fernet, InvalidToken
from redis.asyncio import Redis

PREFIX = "secret:"
TTL_SECONDS = 120
_REF = re.compile(r"^[0-9a-f]{32}$")


class SecretStore(Protocol):
    async def put(self, value: str) -> str:
        """Store a secret for one later `take`; returns an opaque reference."""
        ...

    async def take(self, ref: str) -> str | None:
        """Return and delete the secret, or None if it expired, was taken, or is invalid."""
        ...


def fernet_for(secret_key: str) -> Fernet:
    # Any string works as FINBOARD_SECRET_KEY; derive a proper 32-byte Fernet key from it.
    digest = hashlib.sha256(b"finboard:secret-handoff:v1|" + secret_key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class RedisSecretStore:
    def __init__(self, redis: Redis, secret_key: str, ttl: int = TTL_SECONDS) -> None:
        self._redis = redis
        self._fernet = fernet_for(secret_key)
        self._ttl = ttl

    async def put(self, value: str) -> str:
        ref = uuid.uuid4().hex
        token = self._fernet.encrypt(value.encode("utf-8"))
        await self._redis.set(PREFIX + ref, token, ex=self._ttl)
        return ref

    async def take(self, ref: str) -> str | None:
        if not _REF.match(ref):
            return None
        token = await self._redis.getdel(PREFIX + ref)
        if token is None:
            return None
        try:
            raw = self._fernet.decrypt(token, ttl=self._ttl + 5)
        except InvalidToken:
            return None
        return raw.decode("utf-8")
