"""`inspect-layout` output must not contain any digit or letter from the statement's values."""

import re

import pytest

from finboard.parsers.builtin.generic_table.fixtures import GenericTableFixtures
from finboard.parsers.inspect import inspect_layout, mask
from finboard.parsers.sdk import open_document
from finboard.parsers.sdk.testing import indian_grouping

# "  123.4 | [40-75] 99/99/9999  [105-180] XXX/999999/XXXXX" → keep only the masked words.
_POSITIONS = re.compile(r"^\s*\d+\.\d \| |\[\d+-\d+\] ")


def content(output: str) -> list[str]:
    lines = output.splitlines()
    body = [ln for ln in lines if not ln.startswith(("pages:", "===", "---")) and ln.strip()]
    return [_POSITIONS.sub("", line) for line in body]


def test_mask() -> None:
    assert (
        mask("UPI/412345678901/Swiggy Ltd 1,234.50 Cr") == "XXX/999999999999/XXXXXX XXX 9,999.99 XX"
    )
    assert mask("Ünïcode ₹ 5") == "XXXXXXX ₹ 9"


@pytest.mark.parametrize("seed", [1, 3, 5])
def test_output_contains_no_source_characters(seed: int) -> None:
    data, statement = GenericTableFixtures().build(seed, 30)
    with open_document(data) as doc:
        output = inspect_layout(doc)

    masked = content(output)
    assert masked, "expected some text lines"
    for line in masked:
        assert not re.search(r"[0-8]", line), line
        assert not re.search(r"[^\W\dX_]", line), line  # no letter other than X

    # And none of the actual values appear anywhere, positions included.
    secrets = {statement.institution, statement.account_hint or ""}
    for txn in statement.transactions:
        secrets.add(txn.description)
        secrets.add(indian_grouping(txn.amount))
        secrets.update(txn.description.split())
    for secret in filter(None, secrets):
        if re.search(r"[A-Za-z]", secret) or len(secret) > 3:
            assert secret not in output, secret


def test_keeps_the_structure() -> None:
    data, statement = GenericTableFixtures().build(2, 70)
    with open_document(data) as doc:
        output = inspect_layout(doc)
    assert "=== page 2" in output
    assert "XXXX" in output  # header words
    assert output.count("99/99/9999") >= len(statement.transactions)
