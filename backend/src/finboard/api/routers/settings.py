from fastapi import APIRouter

from finboard.api.deps import SettingsServiceDep
from finboard.api.schemas import Preferences, PreferencesUpdate

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
async def get_preferences(service: SettingsServiceDep) -> Preferences:
    return Preferences.model_validate(await service.get())


@router.patch("")
async def update_preferences(body: PreferencesUpdate, service: SettingsServiceDep) -> Preferences:
    changes = body.model_dump(mode="json", exclude_unset=True)
    return Preferences.model_validate(await service.update(changes))
