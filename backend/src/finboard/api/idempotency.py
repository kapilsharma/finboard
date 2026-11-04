"""`Idempotency-Key` support for retried POSTs (ARCHITECTURE §4).

The first request with a key runs and its response (status + JSON body) is kept in Redis for
24 h per (user, endpoint, key); a retry gets the same response without running again. While the
first is still running, a concurrent retry gets 409. Errors are not cached, so a failed request
can be retried with the same key.
"""

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from finboard.domain.errors import Conflict, ValidationFailed

TTL_SECONDS = 24 * 60 * 60
PENDING_TTL_SECONDS = 120
_PENDING = b"pending"
MAX_KEY_LENGTH = 200


def _redis_key(user_id: uuid.UUID, scope: str, key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"idem:{user_id}:{scope}:{digest}"


async def idempotent(
    redis: Redis,
    *,
    user_id: uuid.UUID,
    scope: str,
    key: str | None,
    status_code: int,
    call: Callable[[], Awaitable[Any]],
) -> JSONResponse:
    if key is None:
        return JSONResponse(jsonable_encoder(await call()), status_code=status_code)
    if not key or len(key) > MAX_KEY_LENGTH:
        raise ValidationFailed(f"Idempotency-Key must be 1-{MAX_KEY_LENGTH} characters")

    rkey = _redis_key(user_id, scope, key)
    if not await redis.set(rkey, _PENDING, nx=True, ex=PENDING_TTL_SECONDS):
        stored = await redis.get(rkey)
        if stored is None or stored == _PENDING:
            raise Conflict("A request with this Idempotency-Key is still being processed")
        cached = json.loads(stored)
        response = JSONResponse(cached["body"], status_code=cached["status"])
        response.headers["Idempotent-Replayed"] = "true"
        return response

    try:
        body = jsonable_encoder(await call())
    except BaseException:
        await redis.delete(rkey)
        raise
    await redis.set(rkey, json.dumps({"status": status_code, "body": body}), ex=TTL_SECONDS)
    return JSONResponse(body, status_code=status_code)
