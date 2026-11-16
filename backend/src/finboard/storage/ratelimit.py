"""Counters in Redis for rate limits (server mode, ADR-0041).

Fixed windows: the first hit starts the window, and the key expires when it ends. That allows
a burst of up to twice the limit across a window boundary, which is fine for what these
protect (password guessing, one user flooding the API). Keys never contain what a user typed:
callers pass ids, or hash anything else with `digest`.
"""

import hashlib

from redis.asyncio import Redis

from finboard.domain.errors import RateLimited


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis

    async def hit(self, key: str, *, limit: int, window: int, detail: str | None = None) -> None:
        """Count one event; raise RateLimited once the window holds more than `limit`.
        A limit of 0 means no limit."""
        if limit <= 0:
            return
        name = f"rl:{key}"
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incr(name)
            pipe.expire(name, window, nx=True)
            pipe.ttl(name)
            count, _, ttl = await pipe.execute()
        if int(count) > limit:
            raise RateLimited(detail, retry_after=max(int(ttl), 1))

    async def count(self, key: str, *, window: int) -> None:
        """Count one event without judging it (a failed sign-in; `check` judges the next)."""
        name = f"rl:{key}"
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.incr(name)
            pipe.expire(name, window, nx=True)
            await pipe.execute()

    async def check(self, key: str, *, limit: int, detail: str | None = None) -> None:
        """Raise if the window is already full, without counting (failures are counted
        separately, after the attempt)."""
        if limit <= 0:
            return
        name = f"rl:{key}"
        count = await self.redis.get(name)
        if count is not None and int(count) >= limit:
            ttl = await self.redis.ttl(name)
            raise RateLimited(detail, retry_after=max(int(ttl), 1))

    async def reset(self, key: str) -> None:
        await self.redis.delete(f"rl:{key}")
