"""Testing kit for adapters (ARCHITECTURE §8, "Synthetic-fixture testing").

Every adapter ships a `FixtureBuilder` that renders the bank's *layout* with *fake data* and
returns the PDF bytes together with the `ParsedStatement` the adapter must produce. Register it
under the `finboard.parser_fixtures` entry-point group with the same name as the parser; the
contract suite (`tests/parsers/test_contract.py`) then runs it automatically.

Fixtures are generated at test time only. Never commit a PDF.
"""

from __future__ import annotations

import calendar
import io
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Protocol

import pikepdf

from finboard.parsers.sdk.model import BalanceKind, ParsedStatement, ParsedTransaction

_CENT = Decimal("0.01")


class FixtureBuilder(Protocol):
    parser_id: str

    def build(
        self, seed: int, rows: int, encrypted_with: str | None = None
    ) -> tuple[bytes, ParsedStatement]:
        """Render a synthetic statement. Same seed → same statement (and, unencrypted, the
        same bytes). `encrypted_with` protects the PDF with that user password."""
        ...


def encrypt_pdf(data: bytes, password: str) -> bytes:
    """Protect a PDF with a user password (AES-256), as banks do."""
    out = io.BytesIO()
    with pikepdf.open(io.BytesIO(data)) as pdf:
        pdf.save(
            out,
            encryption=pikepdf.Encryption(owner=password + "-owner", user=password, R=6),
        )
    return out.getvalue()


@dataclass(frozen=True, slots=True)
class SyntheticRow:
    date: date
    description: str
    amount: Decimal
    direction: str  # "debit" | "credit"
    balance_after: Decimal | None


_MERCHANTS = (
    "SWIGGY LTD",
    "ZOMATO",
    "BIGBASKET",
    "AMAZON PAY",
    "UBER INDIA",
    "IRCTC",
    "APOLLO PHARMACY",
    "RELIANCE FRESH",
    "BOOKMYSHOW",
    "BESCOM",
    "AIRTEL",
    "DMART",
)
_PAYERS = ("ACME CORP", "GLOBEX PVT LTD", "INITECH LLP")


def _description(rng: random.Random, direction: str, kind: BalanceKind) -> str:
    ref = "".join(rng.choice("0123456789") for _ in range(12))
    merchant = rng.choice(_MERCHANTS)
    if kind == "liability":
        if direction == "credit":
            return rng.choice(("PAYMENT RECEIVED - THANK YOU", f"REFUND {merchant}"))
        return rng.choice(
            (f"{merchant} BANGALORE IN", f"{merchant} ONLINE", f"POS {merchant} MUMBAI")
        )
    if direction == "credit":
        return rng.choice(
            (
                f"NEFT-N{ref[:9]}-{rng.choice(_PAYERS)} SALARY FOR THE MONTH",
                f"IMPS/{ref}/REFUND/{merchant}",
                "INTEREST CREDITED",
                f"UPI/{ref}/FRIEND/user{ref[:3]}@okbank/SPLIT DINNER",
            )
        )
    return rng.choice(
        (
            f"UPI/{ref}/{merchant}/{merchant.split()[0].lower()}@ybl/PAYMENT FOR ORDER",
            f"POS XXXX{ref[:4]} {merchant}",
            f"ATM WDL {ref[:6]} MG ROAD",
            f"ECS/LIC PREMIUM/{ref[:8]}",
            f"IMPS/{ref}/RENT/HOUSE OWNER MONTHLY RENT PAYMENT",
            f"ACH D- {rng.choice(_PAYERS)} SIP {ref[:6]}",
        )
    )


def synthetic_statement(
    seed: int,
    rows: int,
    *,
    balance_kind: BalanceKind = "asset",
    institution: str = "Example Bank",
    with_running_balance: bool = True,
) -> tuple[ParsedStatement, list[SyntheticRow]]:
    """Deterministic fake statement data for one month, for fixture builders.

    Returns the expected statement (without `raw`, which the builder fills with the cells it
    rendered) and the rows. Assets keep a positive balance; liabilities track what is owed.
    """
    rng = random.Random(seed)  # noqa: S311 (fake data, not crypto)
    month = 1 + seed % 12
    year = 2025 + (seed // 12) % 2
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    hint = f"{rng.randint(0, 9999):04d}"

    if balance_kind == "asset":
        balance = Decimal(rng.randint(2_000_000, 50_000_000)) / 100
    else:
        balance = Decimal(rng.randint(0, 8_000_000)) / 100
    balance = balance.quantize(_CENT)
    opening = balance

    days = sorted(rng.randint(0, (end - start).days) for _ in range(rows))
    out: list[SyntheticRow] = []
    previous: SyntheticRow | None = None
    for offset in days:
        day = start + timedelta(days=offset)
        if previous is not None and previous.date == day and rng.random() < 0.08:
            # Same text and amount again on the same day: exercises seq_in_day.
            direction, amount, text = previous.direction, previous.amount, previous.description
        else:
            if balance_kind == "asset":
                direction = "credit" if rng.random() < 0.2 else "debit"
            else:
                direction = "credit" if rng.random() < 0.15 else "debit"
            amount = (Decimal(rng.randint(100, 4_000_000)) / 100).quantize(_CENT)
            text = _description(rng, direction, balance_kind)
        # Keep balances sensible: assets don't go negative, liabilities aren't overpaid.
        if balance_kind == "asset" and direction == "debit" and amount > balance:
            direction, text = "credit", _description(rng, "credit", balance_kind)
        if balance_kind == "liability" and direction == "credit" and amount > balance:
            direction, text = "debit", _description(rng, "debit", balance_kind)
        increases = (direction == "credit") == (balance_kind == "asset")
        balance = (balance + amount if increases else balance - amount).quantize(_CENT)
        row = SyntheticRow(
            date=day,
            description=text,
            amount=amount,
            direction=direction,
            balance_after=balance if with_running_balance else None,
        )
        out.append(row)
        previous = row

    statement = ParsedStatement(
        institution=institution,
        balance_kind=balance_kind,
        account_hint=hint,
        period_start=start,
        period_end=end,
        opening_balance=opening,
        closing_balance=balance,
        transactions=[
            ParsedTransaction(
                date=r.date,
                description=r.description,
                amount=r.amount,
                direction="credit" if r.direction == "credit" else "debit",
                balance_after=r.balance_after,
            )
            for r in out
        ],
    )
    return statement, out


def indian_grouping(amount: Decimal) -> str:
    """`Decimal('123456.78')` → `'1,23,456.78'` (lakh grouping), for rendering fixtures."""
    sign = "-" if amount < 0 else ""
    whole, frac = f"{abs(amount):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join([*groups, tail])
    return f"{sign}{whole}.{frac}"
