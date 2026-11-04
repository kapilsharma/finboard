"""Rule matching (ARCHITECTURE §9, ADR-0020). Pure: rules and transactions in, decisions out.

Rules run in `priority, id` order and the first match wins. A rule matches when its pattern
matches the normalised description AND every constraint it sets (account, direction, amount
range) holds. `contains`, `starts_with` and `equals` are plain string operations on the
normalised text; `regex` uses the `regex` package, case-insensitive, with a 50 ms timeout per
evaluation. A rule whose regex times out is switched off for the rest of the run and reported
in `CompiledRules.timed_out`, so the caller can disable and flag it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

import regex

from finboard.categorisation.normalise import normalise

REGEX_TIMEOUT_SECONDS = 0.05
MAX_PATTERN_LENGTH = 500


class MatchKind(StrEnum):
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    EQUALS = "equals"
    REGEX = "regex"


class InvalidPattern(ValueError):
    """The pattern can't be used (empty, too long, or not a valid regular expression)."""


@dataclass(frozen=True, slots=True)
class RuleSpec:
    id: uuid.UUID
    priority: int
    match_kind: MatchKind
    pattern: str
    category_id: uuid.UUID
    account_id: uuid.UUID | None = None
    direction: str | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None


@dataclass(frozen=True, slots=True)
class TxnFacts:
    """What a rule can look at."""

    description_norm: str
    direction: str
    amount: Decimal
    account_id: uuid.UUID | None = None


def match_text(match_kind: MatchKind, pattern: str) -> str:
    """The form of a plain pattern that is compared with normalised text (`swiggy/` → `SWIGGY`).
    Regex patterns are used as written."""
    return pattern if match_kind is MatchKind.REGEX else normalise(pattern)


def validate_pattern(match_kind: MatchKind, pattern: str) -> None:
    """Raise InvalidPattern if the pattern can't be saved (ADR-0020: compiled on save)."""
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise InvalidPattern(f"Patterns can be at most {MAX_PATTERN_LENGTH} characters")
    if match_kind is MatchKind.REGEX:
        if not pattern.strip():
            raise InvalidPattern("The pattern is empty")
        try:
            regex.compile(pattern, regex.IGNORECASE)
        except regex.error as exc:
            raise InvalidPattern(f"Not a valid regular expression: {exc}") from None
    elif not match_text(match_kind, pattern):
        raise InvalidPattern("The pattern is empty once spaces and reference numbers are removed")


@dataclass(slots=True)
class _Compiled:
    spec: RuleSpec
    text: str
    compiled: Any = None  # regex.Pattern[str] for regex rules


@dataclass
class CompiledRules:
    """Rules compiled once per run. Not thread-safe (it records timeouts)."""

    rules: list[_Compiled]
    timed_out: set[uuid.UUID] = field(default_factory=set)
    invalid: set[uuid.UUID] = field(default_factory=set)

    @classmethod
    def compile(cls, specs: Iterable[RuleSpec]) -> CompiledRules:
        rules: list[_Compiled] = []
        invalid: set[uuid.UUID] = set()
        for spec in sorted(specs, key=lambda s: (s.priority, s.id)):
            try:
                validate_pattern(spec.match_kind, spec.pattern)
            except InvalidPattern:
                invalid.add(spec.id)  # e.g. a pattern saved before validation tightened
                continue
            compiled = None
            if spec.match_kind is MatchKind.REGEX:
                compiled = regex.compile(spec.pattern, regex.IGNORECASE)
            rules.append(_Compiled(spec, match_text(spec.match_kind, spec.pattern), compiled))
        return cls(rules=rules, invalid=invalid)

    def first_match(self, txn: TxnFacts) -> RuleSpec | None:
        for rule in self.rules:
            if self._matches(rule, txn):
                return rule.spec
        return None

    def all_matches(self, txn: TxnFacts) -> list[RuleSpec]:
        """Every rule that matches, in order (used to explain shadowing)."""
        return [rule.spec for rule in self.rules if self._matches(rule, txn)]

    def _matches(self, rule: _Compiled, txn: TxnFacts) -> bool:
        spec = rule.spec
        if spec.id in self.timed_out:
            return False
        if spec.direction is not None and spec.direction != txn.direction:
            return False
        if spec.account_id is not None and spec.account_id != txn.account_id:
            return False
        if spec.amount_min is not None and txn.amount < spec.amount_min:
            return False
        if spec.amount_max is not None and txn.amount > spec.amount_max:
            return False
        text = txn.description_norm
        match spec.match_kind:
            case MatchKind.CONTAINS:
                return rule.text in text
            case MatchKind.STARTS_WITH:
                return text.startswith(rule.text)
            case MatchKind.EQUALS:
                return text == rule.text
            case MatchKind.REGEX:
                try:
                    return rule.compiled.search(text, timeout=REGEX_TIMEOUT_SECONDS) is not None
                except TimeoutError:
                    self.timed_out.add(spec.id)
                    return False


def matches(spec: RuleSpec, txns: Sequence[TxnFacts]) -> list[int]:
    """Indexes of the transactions a single rule matches (ignoring other rules)."""
    compiled = CompiledRules.compile([spec])
    return [i for i, txn in enumerate(txns) if compiled.first_match(txn) is not None]
