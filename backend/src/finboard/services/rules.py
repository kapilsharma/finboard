"""Categorisation rules: CRUD, order, test, re-apply, packs (ARCHITECTURE §9, §10).

Re-apply (`rules.apply`, a job) only overwrites what provenance allows: `default` always, `rule`
when scope is `all`, `manual` only with `include_manual` (and only where a rule now matches),
`transfer` never. A dry run returns the diff without changing anything.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from finboard.categorisation.matcher import (
    CompiledRules,
    InvalidPattern,
    RuleSpec,
    TxnFacts,
    validate_pattern,
)
from finboard.categorisation.normalise import normalise
from finboard.db.models import Category, Job, Rule
from finboard.db.repos import TxnFactsRow
from finboard.db.uow import UnitOfWork
from finboard.domain.enums import CategorisedBy, CategoryType, Direction, MatchKind
from finboard.domain.errors import NotFound, PayloadTooLarge, ValidationFailed
from finboard.seed.rules import STARTER_RULES
from finboard.services.categoriser import Categoriser, Decision, rule_spec
from finboard.services.jobs import JobQueue, JobService

log = structlog.get_logger(__name__)

APPLY_TASK = "rules.apply"
PACK_VERSION = 1
MAX_PACK_BYTES = 1024 * 1024
MAX_PACK_RULES = 2000
SAMPLE_SIZE = 20
PATH_SEPARATOR = " / "

_FIELDS = ("match_kind", "pattern", "account_id", "direction", "amount_min", "amount_max")
_UPDATABLE = frozenset({*_FIELDS, "category_id", "label", "enabled"})


class ApplyScope(StrEnum):
    UNCATEGORISED = "uncategorised"
    ALL = "all"


@dataclass(frozen=True, slots=True)
class RuleDraft:
    match_kind: MatchKind
    pattern: str
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    direction: Direction | None = None
    amount_min: Decimal | None = None
    amount_max: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Shadow:
    rule_id: uuid.UUID
    pattern: str
    count: int


@dataclass
class RuleTestResult:
    match_count: int
    would_change: int
    uncategorised: int
    shadowed: int
    shadowed_by: list[Shadow]
    sample: list[TxnFactsRow]


@dataclass
class ApplyDiff:
    changed: int = 0
    by_transition: Counter[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=Counter)
    sample: list[dict[str, Any]] = field(default_factory=list)

    def as_result(
        self, *, dry_run: bool, scanned: int, disabled: Sequence[uuid.UUID]
    ) -> dict[str, Any]:
        return {
            "dry_run": dry_run,
            "scanned": scanned,
            "changed": self.changed,
            "transitions": [
                {"from_category_id": str(a), "to_category_id": str(b), "count": n}
                for (a, b), n in self.by_transition.most_common()
            ],
            "sample": self.sample,
            "disabled_rule_ids": [str(r) for r in disabled],
        }


# ---------------------------------------------------------------- packs (YAML/JSON)


class PackRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    match_kind: MatchKind
    pattern: str = Field(min_length=1, max_length=500)
    category: str = Field(min_length=1, max_length=130, description="Category path")
    category_type: CategoryType
    direction: Direction | None = None
    amount_min: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    amount_max: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    label: str | None = Field(default=None, max_length=120)
    enabled: bool = True

    @field_validator("amount_min", "amount_max", mode="before")
    @classmethod
    def _no_floats(cls, value: Any) -> Any:
        if isinstance(value, float):
            raise ValueError("amounts must be written as strings, e.g. '100.00'")
        return value


class RulePack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finboard_rule_pack: Literal[1]
    rules: list[PackRule] = Field(max_length=MAX_PACK_RULES)


@dataclass(frozen=True, slots=True)
class PackImportResult:
    added: int
    skipped: int
    replaced: int
    categories_created: int


def _now() -> datetime:
    return datetime.now(UTC)


def _facts(row: TxnFactsRow, norm: str | None = None) -> TxnFacts:
    return TxnFacts(
        norm if norm is not None else row.description_norm,
        row.direction.value,
        row.amount,
        row.account_id,
    )


class RuleService:
    def __init__(self, uow: UnitOfWork, queue: JobQueue) -> None:
        self.uow = uow
        self.jobs = JobService(uow, queue)

    # ------------------------------------------------------------ CRUD

    async def list(self) -> Sequence[Rule]:
        return await self.uow.rules.list()

    async def get(self, rule_id: uuid.UUID) -> Rule:
        rule = await self.uow.rules.get(rule_id)
        if rule is None:
            raise NotFound("Rule not found")
        return rule

    async def create(
        self,
        *,
        match_kind: MatchKind,
        pattern: str,
        category_id: uuid.UUID,
        account_id: uuid.UUID | None = None,
        direction: Direction | None = None,
        amount_min: Decimal | None = None,
        amount_max: Decimal | None = None,
        label: str | None = None,
        enabled: bool = True,
    ) -> Rule:
        draft = RuleDraft(
            match_kind, pattern, category_id, account_id, direction, amount_min, amount_max
        )
        await self._validate(draft)
        await self.uow.rules.lock()
        rule = await self.uow.rules.add(
            Rule(
                priority=await self.uow.rules.next_priority(),
                match_kind=match_kind,
                pattern=pattern,
                category_id=category_id,
                account_id=account_id,
                direction=direction,
                amount_min=amount_min,
                amount_max=amount_max,
                label=label,
                enabled=enabled,
            )
        )
        await self.uow.commit()
        return rule

    async def update(self, rule_id: uuid.UUID, changes: Mapping[str, Any]) -> Rule:
        rule = await self._locked(rule_id)
        unknown = set(changes) - _UPDATABLE
        if unknown:
            raise ValueError(f"not updatable: {sorted(unknown)}")
        merged = {f: changes.get(f, getattr(rule, f)) for f in (*_FIELDS, "category_id")}
        await self._validate(RuleDraft(**merged))
        for name, value in changes.items():
            setattr(rule, name, value)
        if set(changes) & {"match_kind", "pattern"} or changes.get("enabled") is True:
            rule.error = None  # the user changed or re-enabled it: give it another chance
        await self.uow.session.flush()
        await self.uow.commit()
        return rule

    async def delete(self, rule_id: uuid.UUID) -> None:
        rule = await self._locked(rule_id)
        await self.uow.rules.delete(rule)
        await self.uow.commit()

    async def reorder(self, ids: Sequence[uuid.UUID]) -> Sequence[Rule]:
        """Set the order of all rules: `ids` must list every rule exactly once."""
        await self.uow.rules.lock()
        current = {r.id for r in await self.uow.rules.list()}
        if len(ids) != len(set(ids)) or set(ids) != current:
            raise ValidationFailed("List every rule exactly once to reorder them")
        await self.uow.rules.set_priorities(ids)
        await self.uow.commit()
        self.uow.session.expire_all()
        return await self.uow.rules.list()

    # ------------------------------------------------------------ test

    async def test(self, draft: RuleDraft, *, rule_id: uuid.UUID | None = None) -> RuleTestResult:
        """What a rule would do: how many transactions it matches, how many of those earlier
        rules already take (shadowing), and how many would change category. `rule_id` tests an
        edit of that rule at its current position; otherwise the rule is tested as a new rule
        appended at the end."""
        await self._validate(draft, require_category=False)
        rules = await self.uow.rules.list(enabled_only=True)
        position = None
        if rule_id is not None:
            existing = await self.get(rule_id)
            position = (existing.priority, existing.id)
        earlier = [
            r
            for r in rules
            if r.id != rule_id and (position is None or (r.priority, r.id) < position)
        ]
        earlier_compiled = CompiledRules.compile(rule_spec(r) for r in earlier)
        candidate = CompiledRules.compile(
            [
                RuleSpec(
                    id=rule_id or uuid.uuid4(),
                    priority=0,
                    match_kind=draft.match_kind,
                    pattern=draft.pattern,
                    category_id=draft.category_id or uuid.UUID(int=0),
                    account_id=draft.account_id,
                    direction=draft.direction.value if draft.direction else None,
                    amount_min=draft.amount_min,
                    amount_max=draft.amount_max,
                )
            ]
        )
        patterns = {r.id: r.pattern for r in earlier}
        matched: list[TxnFactsRow] = []
        shadows: Counter[uuid.UUID] = Counter()
        would_change = uncategorised = 0
        for row in await self.uow.txns.facts():
            facts = _facts(row, normalise(row.description_raw))
            if candidate.first_match(facts) is None:
                continue
            matched.append(row)
            shadow = earlier_compiled.first_match(facts)
            if shadow is not None:
                shadows[shadow.id] += 1
                continue
            if row.categorised_by is CategorisedBy.DEFAULT:
                uncategorised += 1
            if row.categorised_by in (CategorisedBy.DEFAULT, CategorisedBy.RULE) and (
                draft.category_id is None or row.category_id != draft.category_id
            ):
                would_change += 1
        if candidate.timed_out:
            raise ValidationFailed("This regular expression takes too long to run")
        return RuleTestResult(
            match_count=len(matched),
            would_change=would_change,
            uncategorised=uncategorised,
            shadowed=sum(shadows.values()),
            shadowed_by=[Shadow(rid, patterns[rid], n) for rid, n in shadows.most_common()],
            sample=matched[:SAMPLE_SIZE],
        )

    # ------------------------------------------------------------ apply (job)

    async def start_apply(self, *, scope: ApplyScope, include_manual: bool, dry_run: bool) -> Job:
        params = {"scope": scope.value, "include_manual": include_manual, "dry_run": dry_run}
        return await self.jobs.submit(APPLY_TASK, params)

    async def run_apply(self, job: Job) -> dict[str, Any]:
        """Worker side of `rules.apply`. Also rewrites `description_norm` with the current
        normaliser wherever it differs."""
        scope = ApplyScope(job.params.get("scope", ApplyScope.UNCATEGORISED))
        include_manual = bool(job.params.get("include_manual", False))
        dry_run = bool(job.params.get("dry_run", True))
        overwrite = {CategorisedBy.DEFAULT}
        if scope is ApplyScope.ALL:
            overwrite.add(CategorisedBy.RULE)
        if include_manual:
            overwrite.add(CategorisedBy.MANUAL)

        categoriser = await Categoriser.load(self.uow)
        rows = await self.uow.txns.facts()
        diff = ApplyDiff()
        changes: list[dict[str, Any]] = []
        hits: Counter[uuid.UUID] = Counter()
        for row in rows:
            norm = normalise(row.description_raw)
            decision = self._current(row)
            if row.categorised_by in overwrite:
                proposed = categoriser.decide(_facts(row, norm), row.account_type)
                # A manual choice only gives way to a rule that now matches, never to a default.
                if row.categorised_by is not CategorisedBy.MANUAL or proposed.rule_id is not None:
                    decision = proposed
            category_changed = decision.category_id != row.category_id
            if decision.rule_id is not None and decision.rule_id != row.rule_id:
                hits[decision.rule_id] += 1
            if category_changed:
                diff.changed += 1
                diff.by_transition[(row.category_id, decision.category_id)] += 1
                if len(diff.sample) < SAMPLE_SIZE:
                    diff.sample.append(
                        {
                            "transaction_id": str(row.id),
                            "date": row.date.isoformat(),
                            "description": row.description_raw,
                            "amount": f"{row.amount:.2f}",
                            "direction": row.direction.value,
                            "from_category_id": str(row.category_id),
                            "to_category_id": str(decision.category_id),
                        }
                    )
            if (
                category_changed
                or norm != row.description_norm
                or decision.rule_id != row.rule_id
                or decision.categorised_by is not row.categorised_by
                or decision.needs_review != row.needs_review
            ):
                changes.append(
                    {
                        "id": row.id,
                        "category_id": decision.category_id,
                        "type": decision.type,
                        "categorised_by": decision.categorised_by,
                        "rule_id": decision.rule_id,
                        "needs_review": decision.needs_review,
                        "description_norm": norm,
                    }
                )
        disabled = await categoriser.record_timeouts(self.uow)
        if not dry_run:
            for start in range(0, len(changes), 5000):
                await self.uow.txns.set_categories(changes[start : start + 5000])
            await self.uow.rules.add_hits(hits, _now())
            if changes:
                await self.uow.users.bump_data_version(self.uow.user_id)
        log.info("rules.applied", dry_run=dry_run, scanned=len(rows), changed=diff.changed)
        return diff.as_result(dry_run=dry_run, scanned=len(rows), disabled=disabled)

    @staticmethod
    def _current(row: TxnFactsRow) -> Decision:
        return Decision(
            row.category_id, row.type, row.categorised_by, row.rule_id, row.needs_review
        )

    # ------------------------------------------------------------ packs

    async def export_pack(self, fmt: Literal["yaml", "json"]) -> str:
        """All rules, categories by path. Account constraints are left out: packs are for
        sharing, and account ids mean nothing elsewhere."""
        categories = {c.id: c for c in await self.uow.categories.list()}
        rules = []
        for rule in await self.uow.rules.list():
            category = categories[rule.category_id]
            entry: dict[str, Any] = {
                "match_kind": rule.match_kind.value,
                "pattern": rule.pattern,
                "category": _path(category, categories),
                "category_type": category.type.value,
            }
            if rule.direction is not None:
                entry["direction"] = rule.direction.value
            if rule.amount_min is not None:
                entry["amount_min"] = f"{rule.amount_min:.2f}"
            if rule.amount_max is not None:
                entry["amount_max"] = f"{rule.amount_max:.2f}"
            if rule.label:
                entry["label"] = rule.label
            if not rule.enabled:
                entry["enabled"] = False
            rules.append(entry)
        pack = {"finboard_rule_pack": PACK_VERSION, "rules": rules}
        if fmt == "json":
            return json.dumps(pack, indent=2, ensure_ascii=False) + "\n"
        return yaml.safe_dump(pack, sort_keys=False, allow_unicode=True, width=100)

    async def import_pack(
        self, content: str, *, mode: Literal["merge", "replace"]
    ) -> PackImportResult:
        """Add a pack's rules after the existing ones (merge, skipping exact duplicates) or
        instead of them (replace). Missing categories are created from their path and type."""
        if len(content.encode()) > MAX_PACK_BYTES:
            raise PayloadTooLarge("Rule packs can be at most 1 MB")
        pack = _parse_pack(content)
        for index, entry in enumerate(pack.rules, start=1):
            try:
                validate_pattern(entry.match_kind, entry.pattern)
            except InvalidPattern as exc:
                raise ValidationFailed(f"Rule {index}: {exc}") from None
            if (
                entry.amount_min is not None
                and entry.amount_max is not None
                and entry.amount_min > entry.amount_max
            ):
                raise ValidationFailed(f"Rule {index}: the minimum amount is above the maximum")

        await self.uow.rules.lock()
        replaced = 0
        if mode == "replace":
            replaced = len(await self.uow.rules.list())
            await self.uow.rules.delete_all()
        existing = {self._key(r) for r in await self.uow.rules.list()}
        resolver = _CategoryResolver(self.uow, await self.uow.categories.list())
        priority = await self.uow.rules.next_priority()
        added: list[Rule] = []
        skipped = 0
        for entry in pack.rules:
            category = await resolver.get(entry.category, entry.category_type)
            rule = Rule(
                priority=priority + len(added),
                match_kind=entry.match_kind,
                pattern=entry.pattern,
                category_id=category.id,
                direction=entry.direction,
                amount_min=entry.amount_min,
                amount_max=entry.amount_max,
                label=entry.label,
                enabled=entry.enabled,
            )
            key = self._key(rule)
            if key in existing:
                skipped += 1
                continue
            existing.add(key)
            added.append(rule)
        await self.uow.rules.add_all(added)
        await self.uow.commit()
        return PackImportResult(len(added), skipped, replaced, resolver.created)

    async def add_starter_pack(self) -> PackImportResult:
        """Merge the starter rules (seed/rules.py) into the user's rules."""
        categories = {
            c.name.lower(): c for c in await self.uow.categories.list() if not c.parent_id
        }
        entries = []
        for seed in STARTER_RULES:
            category = categories.get(seed.category.lower())
            if category is None:
                continue  # the user renamed or deleted it; skip rather than recreate
            entries.append(
                {
                    "match_kind": seed.match_kind.value,
                    "pattern": seed.pattern,
                    "category": category.name,
                    "category_type": category.type.value,
                    **({"direction": seed.direction.value} if seed.direction else {}),
                }
            )
        pack = {"finboard_rule_pack": PACK_VERSION, "rules": entries}
        return await self.import_pack(json.dumps(pack), mode="merge")

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _key(rule: Rule) -> tuple[Any, ...]:
        return (
            rule.match_kind,
            rule.pattern.strip() if rule.match_kind is MatchKind.REGEX else normalise(rule.pattern),
            rule.category_id,
            rule.account_id,
            rule.direction,
            rule.amount_min,
            rule.amount_max,
        )

    async def _locked(self, rule_id: uuid.UUID) -> Rule:
        rule = await self.uow.rules.get(rule_id, for_update=True)
        if rule is None:
            raise NotFound("Rule not found")
        return rule

    async def _validate(self, draft: RuleDraft, *, require_category: bool = True) -> None:
        try:
            validate_pattern(draft.match_kind, draft.pattern)
        except InvalidPattern as exc:
            raise ValidationFailed(str(exc)) from None
        if draft.category_id is not None:
            if await self.uow.categories.get(draft.category_id) is None:
                raise ValidationFailed("Unknown category")
        elif require_category:
            raise ValidationFailed("Choose a category")
        if draft.account_id is not None and await self.uow.accounts.get(draft.account_id) is None:
            raise ValidationFailed("Unknown account")
        if (
            draft.amount_min is not None
            and draft.amount_max is not None
            and draft.amount_min > draft.amount_max
        ):
            raise ValidationFailed("The minimum amount is above the maximum")


def _path(category: Category, categories: Mapping[uuid.UUID, Category]) -> str:
    if category.parent_id is not None and category.parent_id in categories:
        return categories[category.parent_id].name + PATH_SEPARATOR + category.name
    return category.name


def _parse_pack(content: str) -> RulePack:
    try:
        data = yaml.safe_load(content)  # JSON is valid YAML; safe_load builds plain data only
    except yaml.YAMLError:
        raise ValidationFailed("This isn't a valid YAML or JSON rule pack") from None
    if not isinstance(data, dict):
        raise ValidationFailed("This isn't a Finboard rule pack")
    try:
        return RulePack.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise ValidationFailed(f"Invalid rule pack at {where}: {first['msg']}") from None


class _CategoryResolver:
    """Find a category by path (`Parent / Child`, case-insensitive), creating what's missing."""

    def __init__(self, uow: UnitOfWork, categories: Sequence[Category]) -> None:
        self.uow = uow
        self.by_key = {(c.parent_id, c.name.lower()): c for c in categories}
        self.created = 0

    async def get(self, path: str, type_: CategoryType) -> Category:
        parts = [p.strip() for p in path.split(PATH_SEPARATOR.strip())]
        if not all(parts) or len(parts) > 2 or any(len(p) > 60 for p in parts):
            raise ValidationFailed(f"Invalid category path '{path[:130]}'")
        parent: Category | None = None
        for name in parts:
            key = (parent.id if parent else None, name.lower())
            category = self.by_key.get(key)
            if category is None:
                category = await self.uow.categories.add(
                    Category(name=name, type=type_, parent_id=parent.id if parent else None)
                )
                self.by_key[key] = category
                self.created += 1
            parent = category
        assert parent is not None
        return parent
