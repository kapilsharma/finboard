"""Golden test (ARCHITECTURE §12, ROADMAP M4): the handover sample gives the approved mockup's
September 2026 figures, through the real SQL, metrics and API."""

from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.db.uow import unit_of_work
from finboard.services.demo import load_demo

API = "/api/v1"
HANDOVER = Path(__file__).resolve().parents[4] / "docs" / "handover" / "design"
PACKAGED = Path(__file__).resolve().parents[3] / "src" / "finboard" / "seed" / "demo"


@pytest.fixture
async def september(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> dict[str, Any]:
    async with unit_of_work(sessionmaker, alice.user_id) as uow:
        await load_demo(uow)
    response = await client.get(f"{API}/dashboard", params={"month": "2026-09"})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def test_packaged_sample_matches_the_handover() -> None:
    for name in ("sample-transactions.csv", "budgets.csv"):
        assert (PACKAGED / name).read_bytes() == (HANDOVER / name).read_bytes(), name


async def test_september_2026_headline(september: dict[str, Any]) -> None:
    h = september["headline"]
    assert h["income"]["value"] == "142702.04"
    assert h["spending"]["value"] == "96040.38"
    assert h["net_saving"]["value"] == "46661.66"
    assert h["savings_rate"]["value"] == 32.7
    assert h["net_saving"]["delta"] == "-22330.28"
    assert h["invested"]["value"] == "15000.00"
    assert september["review_count"] == 2
    assert september["prev_month"] == "2026-08"
    # The mockup's other headline numbers: -11.3 % income, +4.6 % spending, -10.2 pts,
    # 32.1 % of net saving invested.
    assert h["income"]["delta_pct"] == -11.3  # -11.2504 exactly: rounded once
    assert h["spending"]["delta_pct"] == 4.6
    assert h["savings_rate"]["delta_pts"] == -10.2
    assert h["invested"]["pct_of_net_saving"] == 32.1


async def test_september_2026_limits(september: dict[str, Any]) -> None:
    categories = september["categories"]
    assert categories["summary"]["over_count"] == 2
    assert categories["summary"] == {
        "spent_in_limits": "89190.38",  # the mockup shows these rounded: ₹89,190, ₹5,810
        "limits_total": "95000.00",
        "left": "5809.62",
        "over_count": 2,
    }
    items = categories["items"]
    # Sorted by % of limit used: the two over-limit categories first, no-limit last.
    assert [i["category"]["name"] for i in items[:2]] == ["Dining out", "Groceries"]
    assert items[0]["status"] == items[1]["status"] == "over"
    assert items[0]["remaining"] == "-93.94"  # "₹94 over" in the mockup
    assert items[-1]["category"]["name"] == "Uncategorized"
    assert items[-1]["status"] == "no_limit" and items[-1]["spent"] == "6850.00"
    assert september["biggest_spend"]["category"]["name"] == "Rent"
    assert september["biggest_spend"]["amount"] == "32000.00"


async def test_september_2026_income_accounts_and_cashflow(september: dict[str, Any]) -> None:
    sources = {s["category"]["name"]: s for s in september["income_sources"]}
    assert set(sources) == {"Salary", "Interest"}
    assert sources["Interest"]["amount"] == "702.04"
    accounts = {a["account"]["name"]: a for a in september["accounts"]}
    assert accounts["Credit card"]["net"].startswith("-32750.")
    assert accounts["Savings account"]["invested"] == "15000.00"
    assert accounts["Savings account"]["net"] == "64411.79"  # ₹64,412 in the mockup
    assert [m["month"] for m in september["cashflow"]] == ["2026-07", "2026-08", "2026-09"]
    assert september["cashflow"][-1]["net_saving"] == "46661.66"
