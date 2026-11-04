from enum import StrEnum


class AccountType(StrEnum):
    SAVINGS = "savings"
    CURRENT = "current"
    CREDIT_CARD = "credit_card"
    LOAN = "loan"
    MUTUAL_FUND = "mutual_fund"
    INSURANCE = "insurance"
    CASH = "cash"
    OTHER = "other"

    @property
    def is_liability(self) -> bool:
        return self in (AccountType.CREDIT_CARD, AccountType.LOAN)


class CategoryType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    INVESTMENT = "investment"
    TRANSFER = "transfer"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_finished(self) -> bool:
        return self in (JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)


class Theme(StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class ImportStatus(StrEnum):
    UPLOADED = "uploaded"  # stored, waiting for a parse slot (per-user cap)
    QUEUED = "queued"
    PROCESSING = "processing"
    NEEDS_PASSWORD = "needs_password"  # noqa: S105 (a status, not a secret)
    PARSED = "parsed"
    COMMITTED = "committed"
    ROLLED_BACK = "rolled_back"
    DISCARDED = "discarded"
    FAILED = "failed"

    @property
    def is_in_flight(self) -> bool:
        return self in (ImportStatus.QUEUED, ImportStatus.PROCESSING)


class ImportSource(StrEnum):
    UPLOAD = "upload"
    WATCHER = "watcher"


class ReconStatus(StrEnum):
    OK = "ok"
    MISMATCH = "mismatch"
    UNVERIFIABLE = "unverifiable"


class Direction(StrEnum):
    DEBIT = "debit"
    CREDIT = "credit"


class CategorisedBy(StrEnum):
    RULE = "rule"
    MANUAL = "manual"
    DEFAULT = "default"
    TRANSFER = "transfer"


class ImportRowOutcome(StrEnum):
    INSERTED = "inserted"
    DUPLICATE = "duplicate"


class MatchKind(StrEnum):
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    EQUALS = "equals"
    REGEX = "regex"


class TransferStatus(StrEnum):
    SUGGESTED = "suggested"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
