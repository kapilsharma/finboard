"""Server-side sessions in Redis, and the auth backend that reads them (ADR-0041).

The browser holds only a random session id, in an HttpOnly SameSite=Strict cookie. Redis maps
its SHA-256 to the user and to the session's CSRF token, so a leaked Redis dump can't be
replayed as cookies, and signing out (or changing a password) ends a session at once.
"""

import hashlib
import hmac
import json
import secrets
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from http.cookies import CookieError, SimpleCookie

from redis.asyncio import Redis

from finboard.auth import Principal
from finboard.domain.errors import CsrfFailed

CSRF_HEADER = "x-csrf-token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_DAY = 24 * 60 * 60


def cookie_name(*, secure: bool) -> str:
    """The `__Host-` prefix makes browsers refuse the cookie unless it is Secure, has
    Path=/ and no Domain, so a sibling subdomain can't plant one. It needs https."""
    return "__Host-finboard_session" if secure else "finboard_session"


@dataclass(frozen=True, slots=True)
class Session:
    principal: Principal
    csrf_token: str
    created_at: float


def _key(token: str) -> str:
    return "session:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _user_key(user_id: uuid.UUID) -> str:
    return f"user-sessions:{user_id}"


class SessionStore:
    def __init__(self, redis: Redis, *, idle_days: int, max_days: int) -> None:
        self.redis = redis
        self.idle_seconds = idle_days * _DAY
        self.max_seconds = max_days * _DAY

    async def create(self, principal: Principal) -> tuple[str, Session]:
        """Start a session. Returns the cookie value and the session."""
        token = secrets.token_urlsafe(32)
        session = Session(principal, secrets.token_urlsafe(32), time.time())
        record = {
            "user_id": str(principal.user_id),
            "username": principal.username,
            "display_name": principal.display_name,
            "csrf": session.csrf_token,
            "created": session.created_at,
        }
        key = _key(token)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(key, json.dumps(record), ex=self.idle_seconds)
            pipe.sadd(_user_key(principal.user_id), key)
            pipe.expire(_user_key(principal.user_id), self.max_seconds)
            await pipe.execute()
        return token, session

    async def get(self, token: str) -> Session | None:
        """The session for a cookie value, with its idle timer restarted."""
        if not token or len(token) > 200:
            return None
        key = _key(token)
        raw = await self.redis.getex(key, ex=self.idle_seconds)
        if raw is None:
            return None
        record = json.loads(raw)
        if time.time() - float(record["created"]) > self.max_seconds:
            await self.redis.delete(key)
            return None
        principal = Principal(
            user_id=uuid.UUID(record["user_id"]),
            username=record["username"],
            display_name=record["display_name"],
        )
        return Session(principal, record["csrf"], float(record["created"]))

    async def delete(self, token: str, user_id: uuid.UUID | None = None) -> None:
        key = _key(token)
        await self.redis.delete(key)
        if user_id is not None:
            await self.redis.srem(_user_key(user_id), key)  # type: ignore[misc]

    async def delete_all(self, user_id: uuid.UUID, *, keep: str | None = None) -> int:
        """End every session of a user (password change, account switched off), except the
        one whose cookie value is `keep`. Returns how many ended."""
        keep_key = _key(keep) if keep else None
        members = await self.redis.smembers(_user_key(user_id))  # type: ignore[misc]
        keys = [m.decode() if isinstance(m, bytes) else m for m in members]
        doomed = [k for k in keys if k != keep_key]
        if doomed:
            await self.redis.delete(*doomed)
            await self.redis.srem(_user_key(user_id), *doomed)  # type: ignore[misc]
        return len(doomed)


def session_cookie(headers: Mapping[str, str], name: str) -> str | None:
    raw = headers.get("cookie")
    if not raw:
        return None
    try:
        jar: SimpleCookie = SimpleCookie(raw)
    except CookieError:
        return None
    morsel = jar.get(name)
    return morsel.value if morsel else None


class SessionBackend:
    """Server mode: the request is whoever its session cookie says it is.

    A request that changes something must also carry the session's CSRF token in
    `X-CSRF-Token`. SameSite=Strict and the `X-Finboard-Client` header (ADR-0015) already stop
    cross-site requests; the token is the defence that doesn't depend on browser behaviour.
    """

    def __init__(self, store: SessionStore, *, cookie: str) -> None:
        self.store = store
        self.cookie = cookie

    async def session(self, headers: Mapping[str, str]) -> Session | None:
        token = session_cookie(headers, self.cookie)
        return await self.store.get(token) if token else None

    async def authenticate(
        self, headers: Mapping[str, str], method: str = "GET"
    ) -> Principal | None:
        session = await self.session(headers)
        if session is None:
            return None
        if method.upper() not in _SAFE_METHODS:
            sent = headers.get(CSRF_HEADER, "")
            if not hmac.compare_digest(sent.encode("utf-8"), session.csrf_token.encode("utf-8")):
                raise CsrfFailed()
        return session.principal
