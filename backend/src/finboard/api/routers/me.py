from fastapi import APIRouter, Request

from finboard.api.deps import PrincipalDep, SettingsDep
from finboard.api.schemas import MeOut
from finboard.auth.sessions import SessionBackend

router = APIRouter(tags=["identity"])


@router.get("/me")
async def me(request: Request, principal: PrincipalDep, settings: SettingsDep) -> MeOut:
    """Who is signed in. 401 `unauthenticated` in server mode when nobody is."""
    backend = request.app.state.auth_backend
    session = (
        await backend.session(request.headers) if isinstance(backend, SessionBackend) else None
    )
    return MeOut(
        id=principal.user_id,
        username=principal.username,
        display_name=principal.display_name,
        mode=settings.mode.value,
        csrf_token=session.csrf_token if session else None,
    )
