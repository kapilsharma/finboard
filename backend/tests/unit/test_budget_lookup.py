"""Budget lookup (ARCHITECTURE §5): a change from month M leaves earlier months unchanged."""

import uuid
from datetime import date
from decimal import Decimal as D

from hypothesis import given
from hypothesis import strategies as st

from finboard.domain.budgets import BudgetEntry, effective_entries, effective_limits

FOOD, RENT = uuid.uuid4(), uuid.uuid4()


def entry(cat: uuid.UUID, month: str, limit: str | None) -> BudgetEntry:
    y, m = (int(p) for p in month.split("-"))
    return BudgetEntry(cat, date(y, m, 1), None if limit is None else D(limit))


HISTORY = [
    entry(FOOD, "2026-07", "4000.00"),
    entry(FOOD, "2026-09", "5000.00"),
    entry(FOOD, "2026-11", None),  # no limit from November
    entry(RENT, "2026-08", "32000.00"),
]


def test_lookup_takes_the_latest_entry_on_or_before_the_month() -> None:
    assert effective_limits(HISTORY, date(2026, 6, 1)) == {}
    assert effective_limits(HISTORY, date(2026, 7, 15)) == {FOOD: D("4000.00")}
    assert effective_limits(HISTORY, date(2026, 8, 1)) == {FOOD: D("4000.00"), RENT: D("32000.00")}
    assert effective_limits(HISTORY, date(2026, 9, 30))[FOOD] == D("5000.00")
    assert effective_limits(HISTORY, date(2026, 10, 1))[FOOD] == D("5000.00")
    assert effective_limits(HISTORY, date(2026, 11, 1))[FOOD] is None  # explicitly no limit
    assert effective_limits(HISTORY, date(2027, 3, 1))[RENT] == D("32000.00")


def test_order_of_history_does_not_matter() -> None:
    assert effective_entries(reversed(HISTORY), date(2026, 10, 1)) == effective_entries(
        HISTORY, date(2026, 10, 1)
    )


months = st.dates(min_value=date(2020, 1, 1), max_value=date(2030, 12, 1)).map(
    lambda d: d.replace(day=1)
)


@given(
    history=st.lists(st.tuples(months, st.decimals(0, 10**6, places=2)), max_size=12),
    change_month=months,
    new_limit=st.decimals(0, 10**6, places=2),
    probe=months,
)
def test_a_change_from_month_m_leaves_earlier_months_unchanged(
    history: list[tuple[date, D]], change_month: date, new_limit: D, probe: date
) -> None:
    before = [BudgetEntry(FOOD, m, limit) for m, limit in history]
    after = [e for e in before if e.effective_from != change_month]
    after.append(BudgetEntry(FOOD, change_month, new_limit))
    if probe < change_month:
        assert effective_limits(after, probe) == effective_limits(before, probe)
    elif not any(change_month < e.effective_from <= probe for e in after):
        assert effective_limits(after, probe)[FOOD] == new_limit  # in force from M on
