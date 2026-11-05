"""API contract (request/response models). Separate from ORM models on purpose (ADR-0007)."""

import datetime as dt
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    SecretStr,
    StringConstraints,
    WithJsonSchema,
    model_validator,
)

from finboard.domain.enums import (
    AccountType,
    CategorisedBy,
    CategoryType,
    Direction,
    ImportSource,
    ImportStatus,
    JobStatus,
    MatchKind,
    ReconStatus,
    Theme,
    TransferStatus,
)

# Money leaves the API as a decimal string with 2 places, never a float (ADR-0008).
Money = Annotated[
    Decimal,
    PlainSerializer(lambda v: f"{v:.2f}", return_type=str),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+\.\d{2}$", "examples": ["2350.00"]}),
]

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
CategoryName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Colour = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]
MaskedNumber = Annotated[
    str, StringConstraints(pattern=r"^[0-9]{1,4}$"), Field(description="Last 4 digits only")
]
ParserId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,64}$")]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PatchModel(InputModel):
    """PATCH bodies: only fields that were sent are applied. Listed fields can't be set to null."""

    not_nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _reject_null_for_required(self) -> Self:
        for field in self.not_nullable & self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"'{field}' can't be null")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class OutputModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- accounts


class AccountCreate(InputModel):
    name: Name
    type: AccountType
    institution: Name | None = None
    masked_number: MaskedNumber | None = None
    parser_id: ParserId | None = None
    active: bool = True
    colour: Colour | None = None


class AccountUpdate(PatchModel):
    not_nullable = frozenset({"name", "type", "active"})

    name: Name | None = None
    type: AccountType | None = None
    institution: Name | None = None
    masked_number: MaskedNumber | None = None
    parser_id: ParserId | None = None
    active: bool | None = None
    colour: Colour | None = None


class AccountOut(OutputModel):
    id: uuid.UUID
    name: str
    type: AccountType
    institution: str | None
    masked_number: str | None
    parser_id: str | None
    currency: str
    active: bool
    colour: str | None
    created_at: datetime
    updated_at: datetime


class AccountList(BaseModel):
    items: list[AccountOut]


# ---------------------------------------------------------------- categories


class CategoryCreate(InputModel):
    name: CategoryName
    type: CategoryType
    parent_id: uuid.UUID | None = None
    colour: Colour | None = None


class CategoryUpdate(PatchModel):
    not_nullable = frozenset({"name", "type", "sort_order", "archived"})

    name: CategoryName | None = None
    type: CategoryType | None = None
    parent_id: uuid.UUID | None = None
    colour: Colour | None = None
    sort_order: int | None = None
    archived: bool | None = None


class CategoryOut(OutputModel):
    id: uuid.UUID
    name: str
    type: CategoryType
    parent_id: uuid.UUID | None
    colour: str | None
    is_system: bool
    system_key: str | None
    sort_order: int
    archived: bool


class CategoryList(BaseModel):
    items: list[CategoryOut]


class CategoryMergeIn(InputModel):
    into_id: uuid.UUID


class CategoryMergeOut(BaseModel):
    into: CategoryOut
    transactions: int
    rules: int
    budgets: int


# ---------------------------------------------------------------- jobs


class JobOut(OutputModel):
    id: uuid.UUID
    kind: str
    status: JobStatus
    progress: int
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class JobList(BaseModel):
    items: list[JobOut]


# ---------------------------------------------------------------- me / meta / settings


class MeOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    mode: str


class MetricDefinitionOut(BaseModel):
    label: str
    formula: str
    tooltip: str


class MetaOut(BaseModel):
    version: str
    api_version: str
    mode: str
    metric_definitions: dict[str, MetricDefinitionOut] = Field(
        description="The metric spec (ARCHITECTURE §12); the UI shows these as tooltips"
    )


class Preferences(BaseModel):
    theme: Theme


class PreferencesUpdate(PatchModel):
    not_nullable = frozenset({"theme"})

    theme: Theme | None = None


class HealthOut(BaseModel):
    status: str
    checks: dict[str, str] = {}


# ---------------------------------------------------------------- parsers


class ParserOut(BaseModel):
    id: str
    name: str
    version: str
    institutions: list[str]
    account_types: list[str]
    file_types: list[str]
    fallback: bool
    enabled: bool = Field(description="Your choice: may detection pick this parser?")
    options: dict[str, Any] = Field(description="Your options for this parser")
    options_schema: dict[str, Any] | None = Field(
        description="JSON Schema of the parser's options (null: it has none)"
    )


class ParserSettingUpdate(PatchModel):
    not_nullable = frozenset({"enabled", "options"})

    enabled: bool | None = None
    options: dict[str, Any] | None = None


class ParserLoadFailure(BaseModel):
    source: str
    reason: str


class ParserList(BaseModel):
    items: list[ParserOut]
    failures: list[ParserLoadFailure]


# ---------------------------------------------------------------- imports


class ParserRef(BaseModel):
    id: str
    version: str | None
    confidence: float | None


class ParserCandidate(BaseModel):
    id: str
    name: str
    confidence: float


class AccountRef(BaseModel):
    id: uuid.UUID
    name: str
    type: AccountType
    masked_number: str | None


class AccountDraft(InputModel):
    name: Name
    type: AccountType
    institution: Name | None = None
    masked_number: MaskedNumber | None = None


class AccountSuggestion(BaseModel):
    create: AccountDraft


class Period(BaseModel):
    start: date | None
    end: date | None


class Reconciliation(BaseModel):
    status: ReconStatus
    balance_kind: str | None
    credits: Money | None
    debits: Money | None
    expected_closing: Money | None
    diff: Money | None
    first_break_seq: int | None
    overridden: bool


class ImportCounts(BaseModel):
    parsed: int
    new: int
    duplicate: int
    excluded: int
    possible_duplicate: int
    needs_review: int


class CommitResult(BaseModel):
    inserted: int
    skipped: int
    excluded: int


class StagedRowOut(BaseModel):
    seq: int
    date: dt.date
    value_date: dt.date | None
    description: str
    amount: Money
    direction: Direction
    balance_after: Money | None
    include: bool
    duplicate: bool
    possible_duplicate: bool
    category_id: uuid.UUID | None
    categorised_by: CategorisedBy | None
    rule_id: uuid.UUID | None = None


class AlreadyImported(BaseModel):
    import_id: uuid.UUID
    committed_at: datetime | None


class ImportOut(BaseModel):
    id: uuid.UUID
    status: ImportStatus
    source: ImportSource
    file_name: str
    file_size: int
    encrypted: bool
    archived: bool
    created_at: datetime
    committed_at: datetime | None
    rolled_back_at: datetime | None
    error: str | None
    job: JobOut | None
    parser: ParserRef | None
    candidates: list[ParserCandidate]
    institution: str | None
    account: AccountRef | None
    account_suggestion: AccountSuggestion | None
    period: Period | None
    opening: Money | None
    closing: Money | None
    reconciliation: Reconciliation | None
    counts: ImportCounts | None
    result: CommitResult | None
    rows: list[StagedRowOut] | None = None
    warnings: list[str]
    file_already_imported: AlreadyImported | None


class ImportList(BaseModel):
    items: list[ImportOut]
    next_cursor: str | None


class UnlockIn(InputModel):
    password: Annotated[SecretStr, Field(min_length=1, max_length=256)]


class ReparseIn(InputModel):
    parser_id: ParserId | None = None
    account_id: uuid.UUID | None = None


class StagedRowUpdate(PatchModel):
    not_nullable = frozenset({"include"})

    include: bool | None = None
    category_id: uuid.UUID | None = None


class CommitIn(InputModel):
    override_reconciliation: bool = False
    create_account: AccountDraft | None = None


# ---------------------------------------------------------------- categorisation (§9, §10)


def _no_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError('send amounts as decimal strings, e.g. "2350.00"')
    return value


# Money in: a decimal string (or integer), >= 0, at most 2 places. Floats are refused (ADR-0008).
MoneyIn = Annotated[
    Decimal,
    BeforeValidator(_no_float),
    Field(ge=0, max_digits=14, decimal_places=2),
    WithJsonSchema({"type": "string", "pattern": r"^\d+(\.\d{1,2})?$", "examples": ["500.00"]}),
]
Pattern = Annotated[str, StringConstraints(min_length=1, max_length=500)]
Label = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]


class TxnOut(OutputModel):
    id: uuid.UUID
    account_id: uuid.UUID
    import_id: uuid.UUID | None
    date: dt.date
    description: str = Field(validation_alias="description_raw")
    description_norm: str
    payee_label: str | None
    amount: Money
    direction: Direction
    category_id: uuid.UUID
    type: CategoryType
    categorised_by: CategorisedBy
    rule_id: uuid.UUID | None
    needs_review: bool
    notes: str | None


class TxnBrief(BaseModel):
    """A matched transaction in a rule test."""

    id: uuid.UUID
    account_id: uuid.UUID
    date: dt.date
    description: str
    amount: Money
    direction: Direction
    category_id: uuid.UUID
    categorised_by: CategorisedBy


class TxnUpdate(PatchModel):
    not_nullable = frozenset({"category_id"})

    category_id: uuid.UUID | None = None
    notes: Annotated[str, StringConstraints(max_length=2000)] | None = None
    payee_label: Label | None = None


class TxnBulkIn(InputModel):
    ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=1000)]
    category_id: uuid.UUID


class TxnBulkOut(BaseModel):
    updated: int


class RuleCreate(InputModel):
    match_kind: MatchKind
    pattern: Pattern
    category_id: uuid.UUID
    account_id: uuid.UUID | None = None
    direction: Direction | None = None
    amount_min: MoneyIn | None = None
    amount_max: MoneyIn | None = None
    label: Label | None = None
    enabled: bool = True


class RuleUpdate(PatchModel):
    not_nullable = frozenset({"match_kind", "pattern", "category_id", "enabled"})

    match_kind: MatchKind | None = None
    pattern: Pattern | None = None
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    direction: Direction | None = None
    amount_min: MoneyIn | None = None
    amount_max: MoneyIn | None = None
    label: Label | None = None
    enabled: bool | None = None


class RuleOut(OutputModel):
    id: uuid.UUID
    priority: int
    match_kind: MatchKind
    pattern: str
    category_id: uuid.UUID
    account_id: uuid.UUID | None
    direction: Direction | None
    amount_min: Money | None
    amount_max: Money | None
    label: str | None
    enabled: bool
    hits: int
    last_hit_at: datetime | None
    error: str | None = Field(description="Why the rule was switched off automatically")
    created_at: datetime
    updated_at: datetime


class RuleList(BaseModel):
    items: list[RuleOut]


class RuleReorderIn(InputModel):
    ids: Annotated[list[uuid.UUID], Field(max_length=5000)]


class RuleTestIn(InputModel):
    match_kind: MatchKind
    pattern: Pattern
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    direction: Direction | None = None
    amount_min: MoneyIn | None = None
    amount_max: MoneyIn | None = None
    rule_id: uuid.UUID | None = Field(
        default=None, description="Test an edit of this rule at its current position"
    )


class ShadowOut(BaseModel):
    rule_id: uuid.UUID
    pattern: str
    count: int


class RuleTestOut(BaseModel):
    match_count: int = Field(description="Transactions the pattern and constraints match")
    would_change: int = Field(description="Of those, how many would get a different category")
    uncategorised: int = Field(description="Matches that are uncategorised now")
    shadowed: int = Field(description="Matches an earlier rule takes first")
    shadowed_by: list[ShadowOut]
    sample: list[TxnBrief]


class ApplyScopeName(StrEnum):
    UNCATEGORISED = "uncategorised"
    ALL = "all"


class RuleApplyIn(InputModel):
    scope: ApplyScopeName = ApplyScopeName.UNCATEGORISED
    include_manual: bool = False
    dry_run: bool = True


class JobAccepted(BaseModel):
    job: JobOut


class RulePackImportIn(InputModel):
    content: Annotated[str, StringConstraints(min_length=1, max_length=1024 * 1024)]
    mode: Literal["merge", "replace"] = "merge"


class RulePackImportOut(BaseModel):
    added: int
    skipped: int
    replaced: int
    categories_created: int


class RuleSuggestionOut(BaseModel):
    match_kind: MatchKind
    pattern: str


class ReviewGroupOut(BaseModel):
    key: str
    suggestion: RuleSuggestionOut | None
    count: int
    debits: Money
    credits: Money
    transactions: list[TxnOut]


class ReviewGroupsOut(BaseModel):
    total: int
    groups: list[ReviewGroupOut]


class SuggestRuleIn(InputModel):
    transaction_id: uuid.UUID


class SuggestRuleOut(BaseModel):
    suggestion: RuleSuggestionOut | None
    test: RuleTestOut | None


class TransferSide(BaseModel):
    transaction: TxnOut
    account: AccountRef


class TransferOut(BaseModel):
    id: uuid.UUID
    status: TransferStatus
    score: float
    days_apart: int
    debit: TransferSide
    credit: TransferSide
    created_at: datetime
    decided_at: datetime | None


class TransferList(BaseModel):
    items: list[TransferOut]


# ---------------------------------------------------------------- dashboard (§10, §12)

MonthStr = Annotated[str, Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", examples=["2026-09"])]
Pct = Annotated[float, Field(description="Percent, rounded to 1 place")]


class CategoryRef(BaseModel):
    id: uuid.UUID
    name: str
    type: CategoryType
    colour: str | None


class MoneyWithChange(BaseModel):
    value: Money
    prev: Money | None
    delta_pct: Pct | None


class NetSavingHeadline(BaseModel):
    value: Money
    prev: Money | None
    delta: Money | None


class RateHeadline(BaseModel):
    value: Pct | None
    prev: Pct | None
    delta_pts: Pct | None


class InvestedHeadline(BaseModel):
    value: Money
    pct_of_net_saving: Pct | None


class Headline(BaseModel):
    income: MoneyWithChange
    spending: MoneyWithChange
    net_saving: NetSavingHeadline
    savings_rate: RateHeadline
    invested: InvestedHeadline


class BiggestSpend(BaseModel):
    category: CategoryRef
    amount: Money


class CashflowMonthOut(BaseModel):
    month: MonthStr
    income: Money
    spending: Money
    net_saving: Money
    invested: Money


class LimitsSummaryOut(BaseModel):
    spent_in_limits: Money
    limits_total: Money
    left: Money = Field(description="Σ limit - Σ spent; negative when over in total")
    over_count: int


class CategoryLimitOut(BaseModel):
    category: CategoryRef
    spent: Money
    limit: Money | None
    remaining: Money | None
    pct_used: Pct | None
    status: Literal["under", "over", "no_limit"]


class CategoriesOut(BaseModel):
    summary: LimitsSummaryOut | None
    items: list[CategoryLimitOut]


class IncomeSourceOut(BaseModel):
    category: CategoryRef
    amount: Money
    prev_amount: Money | None


class AccountTotalsOut(BaseModel):
    account: AccountRef
    income: Money
    spending: Money
    invested: Money
    net: Money


class DashboardOut(BaseModel):
    month: MonthStr
    prev_month: MonthStr | None
    headline: Headline
    biggest_spend: BiggestSpend | None
    review_count: int
    cashflow: list[CashflowMonthOut]
    categories: CategoriesOut
    income_sources: list[IncomeSourceOut]
    accounts: list[AccountTotalsOut]


class DashboardMonths(BaseModel):
    months: list[MonthStr] = Field(description="Months with transactions, newest first")


class BudgetOut(OutputModel):
    category_id: uuid.UUID
    effective_from: dt.date
    monthly_limit: Money | None


class BudgetList(BaseModel):
    month: MonthStr
    items: list[BudgetOut]


class BudgetHistory(BaseModel):
    items: list[BudgetOut]


class BudgetPut(InputModel):
    effective_from: MonthStr = Field(description="The month the limit starts in")
    monthly_limit: MoneyIn | None = Field(description="null = no limit from this month on")


class TxnListItem(TxnOut):
    account_name: str
    category_name: str


class TxnSums(BaseModel):
    income: Money
    spending: Money
    invested: Money
    transfers: Money


class TxnListOut(BaseModel):
    items: list[TxnListItem]
    next_cursor: str | None
    total: int
    sums: TxnSums


class DeleteAllIn(InputModel):
    confirm: str = Field(max_length=20, description='Must be exactly "DELETE ALL"')


# ---------------------------------------------------------------- AI (optional, §18)


class AiStatusOut(BaseModel):
    suggestions_available: bool = Field(description="The operator made suggestions available")
    suggestions_enabled: bool = Field(description="You turned them on")
    suggest_method: str
    embed_model: str
    embedded: int
    transactions: int
    ask_available: bool
    ask_enabled: bool
    ask_provider: str
    ask_sql: bool


class AiSettingsIn(PatchModel):
    not_nullable = frozenset({"suggestions", "ask"})

    suggestions: bool | None = None
    ask: bool | None = None


class SuggestionExample(BaseModel):
    id: uuid.UUID
    date: dt.date
    description: str
    amount: Money
    direction: Direction
    similarity: float


class CategorySuggestionOut(BaseModel):
    category: CategoryRef
    confidence: float = Field(description="Share of the neighbours' vote, 0-1")
    examples: list[SuggestionExample]


class SuggestionsOut(BaseModel):
    method: Literal["embedding", "trigram"]
    items: list[CategorySuggestionOut]


# ---------------------------------------------------------------- Ask Finboard (M4a)

Cell = str | int | float | None


class AskIn(InputModel):
    question: str = Field(min_length=3, max_length=500)


class ResultColumnOut(BaseModel):
    name: str
    kind: Literal["text", "month", "date", "money", "count", "number"]


class ChartOut(BaseModel):
    kind: Literal["bar", "grouped_bar", "line", "table"]
    x: str | None = None
    series: str | None = None
    y: str | None = None


class AskResultOut(BaseModel):
    columns: list[ResultColumnOut]
    rows: list[list[Cell]] = Field(description="Money as decimal strings, dates as ISO text")
    truncated: bool


class AskQueryOut(BaseModel):
    id: uuid.UUID
    question: str
    status: Literal["ok", "clarify", "failed"]
    path: Literal["spec", "sql"] | None
    spec: dict[str, Any] | None
    sql: str | None
    chart: ChartOut | None
    clarification: str | None
    error: str | None
    retries: int
    latency_ms: int
    model: str | None
    tokens_in: int | None
    tokens_out: int | None
    created_at: dt.datetime
    pinned: bool = False


class AskOut(BaseModel):
    query: AskQueryOut
    answer: str | None
    result: AskResultOut | None


class AskHistoryOut(BaseModel):
    items: list[AskQueryOut]


class PinIn(InputModel):
    title: str | None = Field(default=None, max_length=200)


class WidgetOut(BaseModel):
    id: uuid.UUID
    title: str
    sort_order: int
    status: Literal["ok", "needs_update", "failed"]
    message: str | None
    query: AskQueryOut
    chart: ChartOut | None
    result: AskResultOut | None


class WidgetListOut(BaseModel):
    items: list[WidgetOut]
