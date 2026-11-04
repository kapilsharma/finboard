from typing import Annotated

from fastapi import APIRouter, Query

from finboard.api.deps import ReviewServiceDep
from finboard.api.routers.rules import test_out
from finboard.api.schemas import (
    ReviewGroupOut,
    ReviewGroupsOut,
    RuleSuggestionOut,
    SuggestRuleIn,
    SuggestRuleOut,
    TxnOut,
)

router = APIRouter(prefix="/review", tags=["review"])

Month = Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", examples=["2026-09"])]


@router.get("/groups")
async def review_groups(service: ReviewServiceDep, month: Month = None) -> ReviewGroupsOut:
    """Transactions that need a category, grouped by the rule the suggester would propose."""
    groups, total = await service.groups(month)
    return ReviewGroupsOut(
        total=total,
        groups=[
            ReviewGroupOut(
                key=g.key,
                suggestion=(
                    RuleSuggestionOut(
                        match_kind=g.suggestion.match_kind, pattern=g.suggestion.pattern
                    )
                    if g.suggestion
                    else None
                ),
                count=len(g.transactions),
                debits=g.debits,
                credits=g.credits,
                transactions=[TxnOut.model_validate(t) for t in g.transactions],
            )
            for g in groups
        ],
    )


@router.post("/suggest-rule")
async def suggest_rule(body: SuggestRuleIn, service: ReviewServiceDep) -> SuggestRuleOut:
    """The rule the suggester proposes for a transaction, with live match counts."""
    suggested = await service.suggest_rule(body.transaction_id)
    if suggested is None:
        return SuggestRuleOut(suggestion=None, test=None)
    return SuggestRuleOut(
        suggestion=RuleSuggestionOut(
            match_kind=suggested.suggestion.match_kind, pattern=suggested.suggestion.pattern
        ),
        test=test_out(suggested.test),
    )
