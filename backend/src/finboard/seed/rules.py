"""Starter rule pack: generic Indian merchants and payment types (no personal data).

New users get these rules (in this order, so specific ones come first). Existing users can add
them from Settings > Rules. Categories are referenced by the default category names in
`seed/categories.py`; patterns are matched against normalised text (upper-case, references
removed), see `categorisation/normalise.py`.
"""

from dataclasses import dataclass

from finboard.domain.enums import Direction, MatchKind

C, R = MatchKind.CONTAINS, MatchKind.REGEX
DR, CR = Direction.DEBIT, Direction.CREDIT


@dataclass(frozen=True, slots=True)
class SeedRule:
    match_kind: MatchKind
    pattern: str
    category: str  # a default category name
    direction: Direction | None = None


STARTER_RULES: tuple[SeedRule, ...] = (
    # Card bill payments move money between own accounts (OQ-6: rules mark them, pairing
    # only suggests).
    SeedRule(R, r"\bCC ?(BILL )?PAY(MENT)?\b", "Card payment"),
    SeedRule(C, "CREDIT CARD BILL", "Card payment"),
    SeedRule(C, "CREDIT CARD PAYMENT", "Card payment"),
    # Investments: all SIPs and mutual funds (OQ-2)
    SeedRule(R, r"\b(SIP|MF|MUTUAL FUNDS?)\b", "Investments", DR),
    SeedRule(R, r"\b(BSE STAR|NSE ?MFSS|CAMS|KFINTECH|ZERODHA|GROWW)\b", "Investments", DR),
    # Insurance: LIC premiums (OQ-26)
    SeedRule(R, r"\bLIC\b", "Insurance", DR),
    SeedRule(C, "LIFE INSURANCE", "Insurance", DR),
    # Cash: ATM withdrawals (OQ-17)
    SeedRule(R, r"\b(ATM|CASH) ?(WDL|WD|WITHDRAWAL)\b", "Cash", DR),
    SeedRule(R, r"^(NFS|ATM)\b", "Cash", DR),
    # Loan EMIs (OQ-25)
    SeedRule(R, r"\bEMI\b", "Loan EMI", DR),
    # Dining out
    SeedRule(C, "SWIGGY", "Dining out", DR),
    SeedRule(C, "ZOMATO", "Dining out", DR),
    SeedRule(C, "DOMINOS", "Dining out", DR),
    SeedRule(C, "MCDONALD", "Dining out", DR),
    # Groceries
    SeedRule(C, "BIGBASKET", "Groceries", DR),
    SeedRule(C, "DMART", "Groceries", DR),
    SeedRule(C, "BLINKIT", "Groceries", DR),
    SeedRule(C, "ZEPTO", "Groceries", DR),
    SeedRule(C, "JIOMART", "Groceries", DR),
    # Transport and fuel
    SeedRule(R, r"\b(HPCL|BPCL|IOCL|INDIAN OIL|BHARAT PETROLEUM)\b", "Transport", DR),
    SeedRule(C, "IRCTC", "Transport", DR),
    SeedRule(R, r"\b(UBER|OLA|RAPIDO)\b", "Transport", DR),
    SeedRule(C, "FASTAG", "Transport", DR),
    # Shopping
    SeedRule(C, "AMAZON", "Shopping", DR),
    SeedRule(C, "FLIPKART", "Shopping", DR),
    SeedRule(C, "MYNTRA", "Shopping", DR),
    SeedRule(C, "AJIO", "Shopping", DR),
    # Utilities, phone and internet
    SeedRule(C, "AIRTEL", "Utilities", DR),
    SeedRule(R, r"\bJIO\b", "Utilities", DR),
    SeedRule(R, r"\b(BSNL|VODAFONE|TATA PLAY)\b", "Utilities", DR),
    SeedRule(R, r"\b(ELECTRICITY|MSEDCL|BESCOM|TATA POWER|ADANI ELEC)", "Utilities", DR),
    # Entertainment
    SeedRule(R, r"\b(NETFLIX|SPOTIFY|HOTSTAR|BOOKMYSHOW|PVR)\b", "Entertainment", DR),
    # Health
    SeedRule(R, r"\b(APOLLO|PHARMEASY|1MG|NETMEDS|PRACTO)\b", "Health", DR),
    # Income
    SeedRule(C, "SALARY", "Salary", CR),
    SeedRule(R, r"\b(INT\.? ?PD|INTEREST)\b", "Interest", CR),
)
