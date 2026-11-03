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
