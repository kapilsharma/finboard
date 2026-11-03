"""Default categories given to every new user (HANDOVER §4.5, plus owner decisions OQ-2/25/26)."""

from dataclasses import dataclass

from finboard.domain.enums import CategoryType


@dataclass(frozen=True, slots=True)
class SeedCategory:
    name: str
    type: CategoryType
    colour: str
    system_key: str | None = None  # set = system category: can be renamed, not deleted


INC, EXP, INV, TRF = (
    CategoryType.INCOME,
    CategoryType.EXPENSE,
    CategoryType.INVESTMENT,
    CategoryType.TRANSFER,
)

DEFAULT_CATEGORIES: tuple[SeedCategory, ...] = (
    SeedCategory("Salary", INC, "#2f6db5"),
    SeedCategory("Interest", INC, "#4a8fd4"),
    SeedCategory("Freelance", INC, "#6aa6e0"),
    SeedCategory("Refunds", INC, "#8fbbe8"),
    SeedCategory("Rent", EXP, "#b5523a"),
    SeedCategory("Loan EMI", EXP, "#c4683c"),
    SeedCategory("Groceries", EXP, "#d08a3a"),
    SeedCategory("Dining out", EXP, "#d9a23f"),
    SeedCategory("Transport", EXP, "#9c7b3c"),
    SeedCategory("Shopping", EXP, "#a65d84"),
    SeedCategory("Utilities", EXP, "#7d6bb0"),
    SeedCategory("Health", EXP, "#3f9b8f"),
    SeedCategory("Entertainment", EXP, "#c75b7a"),
    SeedCategory("Insurance", EXP, "#5f7f99"),
    SeedCategory("Cash", EXP, "#8a8f7a"),
    SeedCategory("Investments", INV, "#2e8b57"),
    SeedCategory("Card payment", TRF, "#9aa0a6", "card_payment"),
    SeedCategory("Own transfer", TRF, "#9aa0a6", "own_transfer"),
    SeedCategory("Account movement", TRF, "#b0b5ba", "account_movement"),
    SeedCategory("Uncategorized", EXP, "#c9c3b6", "uncategorized"),
    SeedCategory("Uncategorized income", INC, "#c9c3b6", "uncategorized_income"),
)
