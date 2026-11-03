from fastapi import APIRouter

from finboard.api.deps import PrincipalDep, SettingsDep
from finboard.api.schemas import MeOut

router = APIRouter(tags=["identity"])


@router.get("/me")
async def me(principal: PrincipalDep, settings: SettingsDep) -> MeOut:
    return MeOut(
        id=principal.user_id,
        username=principal.username,
        display_name=principal.display_name,
        mode=settings.mode.value,
    )
