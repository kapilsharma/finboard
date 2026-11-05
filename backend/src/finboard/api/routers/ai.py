import uuid

from fastapi import APIRouter

from finboard.api.deps import AiSettingsServiceDep, SuggestionServiceDep
from finboard.api.schemas import (
    AiSettingsIn,
    AiStatusOut,
    CategoryRef,
    CategorySuggestionOut,
    SuggestionExample,
    SuggestionsOut,
)
from finboard.services.ai import AiStatus

router = APIRouter(tags=["ai"])


def _status(s: AiStatus) -> AiStatusOut:
    return AiStatusOut(
        suggestions_available=s.suggestions_available,
        suggestions_enabled=s.suggestions_enabled,
        suggest_method=s.suggest_method,
        embed_model=s.embed_model,
        embedded=s.embedded,
        transactions=s.transactions,
        ask_available=s.ask_available,
        ask_enabled=s.ask_enabled,
        ask_provider=s.ask_provider,
        ask_sql=s.ask_sql,
    )


@router.get("/ai/status")
async def ai_status(service: AiSettingsServiceDep) -> AiStatusOut:
    """Which AI features this server offers, and which you turned on (both off by default)."""
    return _status(await service.status())


@router.patch("/ai/settings")
async def update_ai_settings(body: AiSettingsIn, service: AiSettingsServiceDep) -> AiStatusOut:
    """Turn suggestions or Ask Finboard on or off for yourself."""
    changes = body.changes()
    return _status(
        await service.update(suggestions=changes.get("suggestions"), ask=changes.get("ask"))
    )


@router.get("/transactions/{txn_id}/suggestions")
async def transaction_suggestions(
    txn_id: uuid.UUID, service: SuggestionServiceDep
) -> SuggestionsOut:
    """Up to 3 likely categories, from your own categorised transactions that look alike, each
    with its closest examples. Nothing is applied: accepting one is a manual categorisation.
    404 (`ai_off`) unless the server offers suggestions and you turned them on."""
    result = await service.suggest(txn_id)
    return SuggestionsOut(
        method=result.method,
        items=[
            CategorySuggestionOut(
                category=CategoryRef(
                    id=s.category.id,
                    name=s.category.name,
                    type=s.category.type,
                    colour=s.category.colour,
                ),
                confidence=s.confidence,
                examples=[
                    SuggestionExample(
                        id=e.txn_id,
                        date=e.date,
                        description=e.description,
                        amount=e.amount,
                        direction=e.direction,
                        similarity=round(float(e.similarity), 3),
                    )
                    for e in s.examples
                ],
            )
            for s in result.items
        ],
    )
