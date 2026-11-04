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
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

import regex

from finboard.categorisation.normalise import normalise
from finboard.domain.enums import MatchKind

__all__ = ["CompiledRules", "InvalidPattern", "MatchKind", "RuleSpec", "TxnFacts"]

REGEX_TIMEOUT_SECONDS = 0.05
MAX_PATTERN_LENGTH = 500


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
    test: Callable[[str], bool]  # the pattern, compiled into one call
    constrained: bool


def _pattern_test(spec: RuleSpec) -> Callable[[str], bool]:
    text = match_text(spec.match_kind, spec.pattern)
    match spec.match_kind:
        case MatchKind.CONTAINS:
            return lambda value: text in value
        case MatchKind.STARTS_WITH:
            return lambda value: value.startswith(text)
        case MatchKind.EQUALS:
            return text.__eq__
        case MatchKind.REGEX:
            search = regex.compile(spec.pattern, regex.IGNORECASE).search
            return lambda value: search(value, timeout=REGEX_TIMEOUT_SECONDS) is not None


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
            constrained = any(
                v is not None
                for v in (spec.direction, spec.account_id, spec.amount_min, spec.amount_max)
            )
            rules.append(_Compiled(spec, _pattern_test(spec), constrained))
        return cls(rules=rules, invalid=invalid)

    def first_match(self, txn: TxnFacts) -> RuleSpec | None:
        text = txn.description_norm
        for rule in self.rules:
            try:
                if rule.test(text) and (not rule.constrained or _constraints_hold(rule.spec, txn)):
                    return rule.spec
            except TimeoutError:
                self._switch_off(rule)
                return self.first_match(txn)  # the run carries on without it
        return None

    def all_matches(self, txn: TxnFacts) -> list[RuleSpec]:
        """Every rule that matches, in order (used to explain shadowing)."""
        found = []
        for rule in list(self.rules):
            try:
                if rule.test(txn.description_norm) and (
                    not rule.constrained or _constraints_hold(rule.spec, txn)
                ):
                    found.append(rule.spec)
            except TimeoutError:
                self._switch_off(rule)
        return found

    def _switch_off(self, rule: _Compiled) -> None:
        self.timed_out.add(rule.spec.id)
        self.rules = [r for r in self.rules if r is not rule]


def _constraints_hold(spec: RuleSpec, txn: TxnFacts) -> bool:
    return (
        (spec.direction is None or spec.direction == txn.direction)
        and (spec.account_id is None or spec.account_id == txn.account_id)
        and (spec.amount_min is None or txn.amount >= spec.amount_min)
        and (spec.amount_max is None or txn.amount <= spec.amount_max)
    )


def matches(spec: RuleSpec, txns: Sequence[TxnFacts]) -> list[int]:
    """Indexes of the transactions a single rule matches (ignoring other rules)."""
    compiled = CompiledRules.compile([spec])
    return [i for i, txn in enumerate(txns) if compiled.first_match(txn) is not None]
