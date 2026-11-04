"""Normaliser golden cases (ARCHITECTURE §9) and its idempotence."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from finboard.categorisation.normalise import normalise

GOLDEN = [
    # UPI: RRN, VPA and bank code
    (
        "UPI/DR/412345678901/SWIGGY LTD/YESB/swiggy@ybl/Payment",
        "UPI DR SWIGGY LTD YESB SWIGGY YBL PAYMENT",
    ),
    (
        "UPI-ZOMATO-ZOMATO.ORDER@ICICI-ICIC0DC0099-612345678901-UPI",
        "UPI ZOMATO ZOMATO.ORDER ICICI UPI",
    ),
    (
        "upi/cr/512398765432/Ravi Kumar/SBIN/ravi.k@oksbi/rent share",
        "UPI CR RAVI KUMAR SBIN RAVI.K OKSBI RENT SHARE",
    ),
    # NEFT / RTGS: alphanumeric references
    ("NEFT-HDFCN52026091234567-ACME CORP-SALARY SEP", "NEFT ACME CORP SALARY SEP"),
    ("NEFT/N123241234567890/ACME CORP PVT LTD", "NEFT ACME CORP PVT LTD"),
    ("RTGS:UTIBR52026090100123456:HOME BUILDERS", "RTGS HOME BUILDERS"),
    # IMPS
    ("IMPS/P2A/612345678901/Ravi Kumar/HDFC", "IMPS P2A RAVI KUMAR HDFC"),
    ("MMT/IMPS/612345678901/RENT/ANITA S", "MMT IMPS RENT ANITA S"),
    # POS and card masks
    ("POS 4111XXXXXXXX1234 AMAZON IN", "POS AMAZON IN"),
    ("POS/XX1234/DMART AVENUE/PUNE", "POS DMART AVENUE PUNE"),
    ("CARD ****5678 NETFLIX.COM", "CARD NETFLIX.COM"),
    ("VPS*XXXX-4321*HPCL PETROL PUMP", "VPS HPCL PETROL PUMP"),
    # ECS / NACH mandates
    ("ECS/ICICI PRU MF/SIP 1234567", "ECS ICICI PRU MF SIP"),
    ("NACH_DR_LIC OF INDIA_000098765432", "NACH DR LIC OF INDIA"),
    # ATM, interest, bill payments: short numbers (dates, years) stay
    ("ATM WDL XX1234 MG ROAD", "ATM WDL MG ROAD"),
    ("INT.PD:01-09-2026 TO 30-09-2026", "INT.PD 01 09 2026 TO 30 09 2026"),
    ("BIL/ONL/000123456789/AIRTEL/Bill", "BIL ONL AIRTEL BILL"),
    ("CC BILL PAYMENT - 4375XXXXXXXX9012", "CC BILL PAYMENT"),
    # Unicode: NFKC, upper-case, odd whitespace
    ("ﬁ  Café\u00a0Coffee\tDay", "FI CAFÉ COFFEE DAY"),
    ("", ""),
    ("  /// ", ""),
]


@pytest.mark.parametrize(("raw", "expected"), GOLDEN)
def test_golden(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


narration = st.text(
    alphabet=st.sampled_from("ABCXYZabcxyz0123456789 /-*_:@|.\\\u00a0\tßéﬁ"), max_size=80
) | st.text(max_size=60)


@given(narration)
def test_idempotent(raw: str) -> None:
    once = normalise(raw)
    assert normalise(once) == once


@given(narration)
def test_no_reference_numbers_or_separators_survive(raw: str) -> None:
    out = normalise(raw)
    assert out == out.strip()
    assert "  " not in out
    assert not any(sep in out for sep in "/-*_:@|")
    digits_run = 0
    for ch in out:
        digits_run = digits_run + 1 if ch.isdigit() else 0
        assert digits_run < 6
