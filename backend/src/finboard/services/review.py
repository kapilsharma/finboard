"""The review queue (ARCHITECTURE §9, §10): transactions that need a category, grouped by the
token the rule suggester would propose, so similar ones can be categorised together."""

from __future__ import annotations

import calendar
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from finboard.categorisation.suggest import RuleSuggestion, group_key, suggest_rule
from finboard.db.models import Txn
from finboard.db.uow import UnitOfWork
from finboard.domain.enums import Direction
from finboard.domain.errors import NotFound, ValidationFailed
from finboard.services.rules import RuleDraft, RuleService, RuleTestResult

OTHER_GROUP = "Other"


@dataclass
class ReviewGroup:
    key: str
    suggestion: RuleSuggestion | None
    transactions: list[Txn] = field(default_factory=list)
    debits: Decimal = Decimal("0.00")
    credits: Decimal = Decimal("0.00")


@dataclass
class SuggestedRule:
    suggestion: RuleSuggestion
    test: RuleTestResult


def month_range(month: str) -> tuple[date, date]:
    try:
        year, mon = (int(part) for part in month.split("-"))
        start = date(year, mon, 1)
    except ValueError:
        raise ValidationFailed("month must look like 2026-09") from None
    return start, date(year, mon, calendar.monthrange(year, mon)[1])


class ReviewService:
    def __init__(self, uow: UnitOfWork, rules: RuleService) -> None:
        self.uow = uow
        self.rules = rules

    async def groups(self, month: str | None = None) -> tuple[list[ReviewGroup], int]:
        """Groups, largest first; ungroupable transactions last, under "Other"."""
        start, end = month_range(month) if month else (None, None)
        txns = await self.uow.txns.needing_review(start=start, end=end)
        groups: dict[str, ReviewGroup] = {}
        by_key: dict[str, list[Txn]] = defaultdict(list)
        for txn in txns:
            by_key[group_key(txn.description_norm) or OTHER_GROUP].append(txn)
        for key, members in by_key.items():
            group = ReviewGroup(
                key=key,
                suggestion=None
                if key == OTHER_GROUP
                else suggest_rule(members[0].description_norm),
                transactions=members,
            )
            for txn in members:
                if txn.direction is Direction.DEBIT:
                    group.debits += txn.amount
                else:
                    group.credits += txn.amount
            groups[key] = group
        ordered = sorted(
            groups.values(), key=lambda g: (g.key == OTHER_GROUP, -len(g.transactions), g.key)
        )
        return ordered, len(txns)

    async def suggest_rule(self, txn_id: uuid.UUID) -> SuggestedRule | None:
        """The rule the suggester proposes for one transaction, with its live match counts."""
        txn = await self.uow.txns.get(txn_id)
        if txn is None:
            raise NotFound("Transaction not found")
        suggestion = suggest_rule(txn.description_norm)
        if suggestion is None:
            return None
        test = await self.rules.test(RuleDraft(suggestion.match_kind, suggestion.pattern))
        return SuggestedRule(suggestion, test)
