"""Accounts and sign-in for server mode (ADR-0041).

Works on `app_user`, which has no row-level security, through a unit of work that isn't bound
to a user: nobody is signed in yet. Everything else in Finboard runs as a known user.
"""

import asyncio
import re
from dataclasses import dataclass

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal, passwords
from finboard.auth.sessions import Session, SessionStore
from finboard.core.config import Settings
from finboard.db.uow import unit_of_work
from finboard.domain.errors import (
    Conflict,
    InvalidCredentials,
    NotFound,
    SignupClosed,
    ValidationFailed,
)
from finboard.services.users import principal_for, provision_user
from finboard.storage.ratelimit import RateLimiter, digest

log = structlog.get_logger(__name__)

USERNAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,31}$")
MSG_LOCKED = "Too many wrong passwords. Wait a few minutes, then try again."
MSG_SIGNUPS = "Too many new accounts from this address. Try again later."


def normalise_username(username: str) -> str:
    name = username.strip().lower()
    if not USERNAME.match(name):
        raise ValidationFailed(
            "A username is 3 to 32 characters: letters, digits, and . _ - after the first"
        )
    return name


@dataclass(frozen=True)
class AuthLimits:
    signup_open: bool
    login_max_failures: int
    login_max_failures_per_ip: int
    login_window: int
    signup_per_ip_per_hour: int

    @classmethod
    def from_settings(cls, settings: Settings) -> "AuthLimits":
        return cls(
            signup_open=settings.signup == "open",
            login_max_failures=settings.login_max_failures,
            login_max_failures_per_ip=settings.login_max_failures_per_ip,
            login_window=settings.login_window_seconds,
            signup_per_ip_per_hour=settings.signup_per_ip_per_hour,
        )


class AccountAdmin:
    """Creating users and setting passwords. Used by sign-up and by the operator's CLI."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self.sessionmaker = sessionmaker

    async def create_user(self, *, username: str, display_name: str, password: str) -> Principal:
        name = normalise_username(username)
        shown = display_name.strip() or name
        if len(shown) > 120:
            raise ValidationFailed("Use a display name of at most 120 characters")
        passwords.check_policy(password, username=name)
        password_hash = await asyncio.to_thread(passwords.hash_password, password)
        async with unit_of_work(self.sessionmaker) as uow:
            try:
                user = await provision_user(uow, username=name, display_name=shown)
                user.password_hash = password_hash
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise Conflict("That username is taken") from exc
            return principal_for(user)

    async def set_password(self, *, username: str, password: str) -> Principal:
        """Give a user a new password (the operator's reset; also how the `local` user of a
        local-mode database gets one when the server is switched to server mode)."""
        name = username.strip().lower()
        passwords.check_policy(password, username=name)
        password_hash = await asyncio.to_thread(passwords.hash_password, password)
        async with unit_of_work(self.sessionmaker) as uow:
            user = await uow.users.get_by_username(name)
            if user is None:
                raise NotFound("No such user")
            user.password_hash = password_hash
            await uow.commit()
            return principal_for(user)


class AuthService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        sessions: SessionStore,
        limiter: RateLimiter,
        limits: AuthLimits,
    ) -> None:
        self.sessionmaker = sessionmaker
        self.sessions = sessions
        self.limiter = limiter
        self.limits = limits
        self.admin = AccountAdmin(sessionmaker)

    async def signup(
        self, *, username: str, display_name: str, password: str, ip: str
    ) -> tuple[str, Session]:
        if not self.limits.signup_open:
            raise SignupClosed("Ask whoever runs this server to create an account for you.")
        await self.limiter.hit(
            f"signup:ip:{digest(ip)}",
            limit=self.limits.signup_per_ip_per_hour,
            window=3600,
            detail=MSG_SIGNUPS,
        )
        principal = await self.admin.create_user(
            username=username, display_name=display_name, password=password
        )
        log.info("auth.signup", user_id=str(principal.user_id))
        return await self.sessions.create(principal)

    async def login(self, *, username: str, password: str, ip: str) -> tuple[str, Session]:
        name = username.strip().lower()
        user_key = f"login:user:{digest(name)}"
        ip_key = f"login:ip:{digest(ip)}"
        await self.limiter.check(user_key, limit=self.limits.login_max_failures, detail=MSG_LOCKED)
        await self.limiter.check(
            ip_key, limit=self.limits.login_max_failures_per_ip, detail=MSG_LOCKED
        )
        async with unit_of_work(self.sessionmaker) as uow:
            user = await uow.users.get_by_username(name)
            stored = user.password_hash if user is not None and user.is_active else None
            ok = await asyncio.to_thread(passwords.verify_password, stored, password)
            if not ok or user is None:
                # Same answer and same work whether the username or the password was wrong.
                await self.limiter.count(user_key, window=self.limits.login_window)
                await self.limiter.count(ip_key, window=self.limits.login_window)
                log.info("auth.login_failed")
                raise InvalidCredentials()
            if stored is not None and passwords.needs_rehash(stored):
                user.password_hash = await asyncio.to_thread(passwords.hash_password, password)
                await uow.commit()
            principal = principal_for(user)
        await self.limiter.reset(user_key)
        log.info("auth.login", user_id=str(principal.user_id))
        return await self.sessions.create(principal)

    async def logout(self, token: str, principal: Principal | None) -> None:
        await self.sessions.delete(token, principal.user_id if principal else None)

    async def change_password(
        self, principal: Principal, *, current: str, new: str, keep_token: str | None
    ) -> None:
        """Change the signed-in user's password and end their other sessions."""
        key = f"password:user:{principal.user_id}"
        await self.limiter.check(key, limit=self.limits.login_max_failures, detail=MSG_LOCKED)
        async with unit_of_work(self.sessionmaker) as uow:
            user = await uow.users.get(principal.user_id)
            stored = user.password_hash if user is not None else None
            if not await asyncio.to_thread(passwords.verify_password, stored, current):
                await self.limiter.count(key, window=self.limits.login_window)
                raise ValidationFailed("The current password is wrong")
            assert user is not None
            passwords.check_policy(new, username=user.username)
            user.password_hash = await asyncio.to_thread(passwords.hash_password, new)
            await uow.commit()
        await self.limiter.reset(key)
        ended = await self.sessions.delete_all(principal.user_id, keep=keep_token)
        log.info("auth.password_changed", user_id=str(principal.user_id), sessions_ended=ended)
