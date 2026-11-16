"""Sign-up, sign-in and sign-out (server mode, ADR-0041). In local mode there is nothing to
sign in to, and these routes answer 404."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from finboard.api.deps import PrincipalDep, SettingsDep
from finboard.api.schemas import LoginIn, PasswordChangeIn, SessionOut, SignupIn
from finboard.auth.sessions import Session, cookie_name, session_cookie
from finboard.core.config import Settings
from finboard.domain.errors import NotFound
from finboard.services.auth import AuthLimits, AuthService

router = APIRouter(prefix="/auth", tags=["identity"])


def get_auth_service(request: Request) -> AuthService:
    state = request.app.state
    if state.sessions is None:
        raise NotFound("This Finboard runs in local mode: there is no sign-in")
    return AuthService(
        state.sessionmaker, state.sessions, state.limiter, AuthLimits.from_settings(state.settings)
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def _client_ip(request: Request) -> str:
    # With a trusted proxy configured (FINBOARD_FORWARDED_ALLOW_IPS), uvicorn has already
    # replaced this with the address from X-Forwarded-For.
    return request.client.host if request.client else "unknown"


def _set_cookie(response: Response, settings: Settings, token: str) -> None:
    response.set_cookie(
        cookie_name(secure=settings.cookie_secure),
        token,
        max_age=settings.session_max_days * 24 * 60 * 60,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _session_out(session: Session) -> SessionOut:
    return SessionOut(
        id=session.principal.user_id,
        username=session.principal.username,
        display_name=session.principal.display_name,
        csrf_token=session.csrf_token,
    )


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    body: SignupIn,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> SessionOut:
    """Create an account and sign in. 403 `signup_closed` unless the operator opened sign-up."""
    token, session = await service.signup(
        username=body.username,
        display_name=body.display_name or "",
        password=body.password.get_secret_value(),
        ip=_client_ip(request),
    )
    _set_cookie(response, settings, token)
    return _session_out(session)


@router.post("/login")
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> SessionOut:
    """Sign in. The session id arrives as an HttpOnly cookie; the CSRF token in the body goes
    back in `X-CSRF-Token` on every request that changes something."""
    token, session = await service.login(
        username=body.username, password=body.password.get_secret_value(), ip=_client_ip(request)
    )
    _set_cookie(response, settings, token)
    return _session_out(session)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, service: AuthServiceDep, settings: SettingsDep
) -> None:
    """End this session. Works without a valid session too, so a stale tab can sign out."""
    name = cookie_name(secure=settings.cookie_secure)
    token = session_cookie(request.headers, name)
    if token:
        session = await service.sessions.get(token)
        await service.logout(token, session.principal if session else None)
    response.delete_cookie(name, path="/", httponly=True, secure=settings.cookie_secure)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChangeIn,
    request: Request,
    principal: PrincipalDep,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> None:
    """Change your password. Your other sessions are signed out; this one stays."""
    await service.change_password(
        principal,
        current=body.current_password.get_secret_value(),
        new=body.new_password.get_secret_value(),
        keep_token=session_cookie(request.headers, cookie_name(secure=settings.cookie_secure)),
    )
