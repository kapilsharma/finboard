"""The categorisation engine bound to one user's data (ARCHITECTURE §9).

`Categoriser.load` reads the user's enabled rules and the fallback categories once; `decide`
then categorises any number of transactions without further I/O. Used at parse time (staged
rows), at commit, by `rules.apply`, by `/rules/test` and when a transfer pair is undone.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import structlog

from finboard.categorisation.matcher import CompiledRules, RuleSpec, TxnFacts
from finboard.db.models import Category, Rule
from finboard.db.uow import UnitOfWork
from finboard.domain.enums import AccountType, CategorisedBy, CategoryType, Direction
from finboard.domain.errors import Conflict

log = structlog.get_logger(__name__)

REGEX_TIMEOUT_ERROR = "Switched off: its regular expression took too long (over 50 ms) to run"

# Rows of loan, insurance and mutual-fund statements move money the bank side already counted
# (OQ-25): they default to the transfer-type *Account movement* and need no review.
MOVEMENT_ACCOUNT_TYPES = frozenset(
    {AccountType.LOAN, AccountType.INSURANCE, AccountType.MUTUAL_FUND}
)


@dataclass(frozen=True, slots=True)
class Decision:
    category_id: uuid.UUID
    type: CategoryType
    categorised_by: CategorisedBy
    rule_id: uuid.UUID | None
    needs_review: bool


def rule_spec(rule: Rule) -> RuleSpec:
    return RuleSpec(
        id=rule.id,
        priority=rule.priority,
        match_kind=rule.match_kind,
        pattern=rule.pattern,
        category_id=rule.category_id,
        account_id=rule.account_id,
        direction=rule.direction.value if rule.direction else None,
        amount_min=rule.amount_min,
        amount_max=rule.amount_max,
    )


class Categoriser:
    def __init__(
        self,
        rules: CompiledRules,
        categories: dict[uuid.UUID, Category],
        fallbacks: dict[str, Category],
    ) -> None:
        self.rules = rules
        self.categories = categories
        self.fallbacks = fallbacks

    @classmethod
    async def load(cls, uow: UnitOfWork, *, rules: Sequence[Rule] | None = None) -> Categoriser:
        """`rules` overrides the user's enabled rules (e.g. to test a draft)."""
        if rules is None:
            rules = await uow.rules.list(enabled_only=True)
        categories = {c.id: c for c in await uow.categories.list()}
        fallbacks: dict[str, Category] = {}
        for key in ("uncategorized", "uncategorized_income", "account_movement"):
            category = next((c for c in categories.values() if c.system_key == key), None)
            if category is None:
                raise Conflict(f"The system category '{key}' is missing")
            fallbacks[key] = category
        return cls(CompiledRules.compile(rule_spec(r) for r in rules), categories, fallbacks)

    def match(self, facts: TxnFacts) -> RuleSpec | None:
        return self.rules.first_match(facts)

    def decide(self, facts: TxnFacts, account_type: AccountType | None = None) -> Decision:
        rule = self.rules.first_match(facts)
        if rule is not None:
            category = self.categories.get(rule.category_id)
            if category is not None:
                return Decision(category.id, category.type, CategorisedBy.RULE, rule.id, False)
        return self.default(facts.direction, account_type)

    def default(self, direction: str, account_type: AccountType | None = None) -> Decision:
        if account_type in MOVEMENT_ACCOUNT_TYPES:
            category = self.fallbacks["account_movement"]
            return Decision(category.id, category.type, CategorisedBy.DEFAULT, None, False)
        key = "uncategorized" if direction == Direction.DEBIT else "uncategorized_income"
        category = self.fallbacks[key]
        return Decision(category.id, category.type, CategorisedBy.DEFAULT, None, True)

    def category(self, category_id: uuid.UUID) -> Category | None:
        return self.categories.get(category_id)

    async def record_timeouts(self, uow: UnitOfWork) -> list[uuid.UUID]:
        """Switch off rules whose regex timed out during this run, with a reason (ADR-0020).
        The caller commits."""
        timed_out = sorted(self.rules.timed_out)
        if timed_out:
            await uow.rules.disable(timed_out, REGEX_TIMEOUT_ERROR)
            log.warning("rules.regex_timeout", rule_ids=[str(r) for r in timed_out])
        return timed_out
