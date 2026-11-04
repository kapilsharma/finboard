from fastapi import APIRouter

from finboard.api.deps import PrincipalDep, RegistryDep
from finboard.api.schemas import ParserList, ParserLoadFailure, ParserOut
from finboard.parsers.registry import is_fallback

router = APIRouter(prefix="/parsers", tags=["parsers"])


@router.get("")
async def list_parsers(registry: RegistryDep, _principal: PrincipalDep) -> ParserList:
    """Installed parsers, plus any that failed to load and why (ADR-0009)."""
    return ParserList(
        items=[
            ParserOut(
                id=p.id,
                name=p.name,
                version=p.version,
                institutions=list(p.institutions),
                account_types=list(p.account_types),
                file_types=list(p.file_types),
                fallback=is_fallback(p),
            )
            for p in registry.all()
        ],
        failures=[ParserLoadFailure(source=f.source, reason=f.reason) for f in registry.failures],
    )
