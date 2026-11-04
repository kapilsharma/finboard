from fastapi import APIRouter

from finboard.api.deps import RegistryDep, UowDep
from finboard.api.schemas import ParserList, ParserLoadFailure, ParserOut, ParserSettingUpdate
from finboard.parsers.registry import is_fallback
from finboard.services.parser_settings import (
    ParserChoice,
    ParserSettingsService,
    options_json_schema,
)

router = APIRouter(prefix="/parsers", tags=["parsers"])


def _out(choice: ParserChoice) -> ParserOut:
    p = choice.parser
    return ParserOut(
        id=p.id,
        name=p.name,
        version=p.version,
        institutions=list(p.institutions),
        account_types=list(p.account_types),
        file_types=list(p.file_types),
        fallback=is_fallback(p),
        enabled=choice.enabled,
        options=choice.options,
        options_schema=options_json_schema(p),
    )


@router.get("")
async def list_parsers(registry: RegistryDep, uow: UowDep) -> ParserList:
    """Installed parsers with your settings, plus any that failed to load and why (ADR-0009)."""
    choices = await ParserSettingsService(uow, registry).choices()
    return ParserList(
        items=[_out(c) for c in choices],
        failures=[ParserLoadFailure(source=f.source, reason=f.reason) for f in registry.failures],
    )


@router.patch("/{parser_id}")
async def update_parser(
    parser_id: str, body: ParserSettingUpdate, registry: RegistryDep, uow: UowDep
) -> ParserOut:
    """Switch a parser on or off for detection, or set its options (validated against the
    parser's own options schema)."""
    changes = body.changes()
    choice = await ParserSettingsService(uow, registry).update(
        parser_id, enabled=changes.get("enabled"), options=changes.get("options")
    )
    return _out(choice)
