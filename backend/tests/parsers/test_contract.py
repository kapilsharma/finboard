"""Contract suite (ARCHITECTURE §8): every registered adapter x several seeds.

Pure (no database), so it runs on Linux, macOS and Windows. Adding a parser to the
`finboard.parsers` entry points, and its builder to `finboard.parser_fixtures`, is all it takes
for these tests to cover it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import cache
from importlib.metadata import entry_points

import pytest

from finboard.domain.reconcile import ReconRow, reconcile
from finboard.parsers.builtin._template.fixtures import ExampleBankFixtures
from finboard.parsers.builtin._template.parser import ExampleBankSavingsParser
from finboard.parsers.registry import (
    FIXTURE_ENTRY_POINT_GROUP,
    ParserRegistry,
    is_fallback,
)
from finboard.parsers.sdk import (
    PARSER_API_VERSION,
    ParsedStatement,
    PasswordRequired,
    StatementParser,
    WrongPassword,
    open_document,
)
from finboard.parsers.sdk.testing import FixtureBuilder

# (seed, rows): small, multi-page and empty statements; seeds also pick layout variants.
CASES = [(1, 12), (2, 70), (3, 25), (4, 1), (5, 0), (6, 40), (9, 33)]
PASSWORD = "Fixture#2026"


@dataclass(frozen=True)
class Adapter:
    parser: StatementParser
    builder: FixtureBuilder


@cache
def registry() -> ParserRegistry:
    return ParserRegistry.from_entry_points()


@cache
def adapters() -> tuple[Adapter, ...]:
    builders: dict[str, FixtureBuilder] = {}
    for ep in entry_points(group=FIXTURE_ENTRY_POINT_GROUP):
        builder = ep.load()()
        builders[builder.parser_id] = builder
    found = [Adapter(p, builders[p.id]) for p in registry().all() if p.id in builders]
    # The contributor template isn't registered, but it must keep working.
    found.append(Adapter(ExampleBankSavingsParser(), ExampleBankFixtures()))
    return tuple(found)


@cache
def fixture(parser_id: str, seed: int, rows: int) -> tuple[bytes, ParsedStatement]:
    adapter = next(a for a in adapters() if a.parser.id == parser_id)
    return adapter.builder.build(seed, rows)


def _ids() -> list[str]:
    return [a.parser.id for a in adapters()]


def _cases() -> list[tuple[str, int, int]]:
    return [(a.parser.id, seed, rows) for a in adapters() for seed, rows in CASES]


def _parser(parser_id: str) -> StatementParser:
    return next(a.parser for a in adapters() if a.parser.id == parser_id)


def test_registry_loads_cleanly() -> None:
    assert registry().failures == []
    assert "generic_table" in registry()


@pytest.mark.parametrize("parser_id", [p.id for p in registry().all()])
def test_every_registered_parser_has_a_fixture_builder(parser_id: str) -> None:
    assert parser_id in _ids(), f"{parser_id}: register a builder under {FIXTURE_ENTRY_POINT_GROUP}"


@pytest.mark.parametrize("parser_id", _ids())
def test_metadata(parser_id: str) -> None:
    parser = _parser(parser_id)
    assert parser.api_version == PARSER_API_VERSION
    assert parser.id.isidentifier() and parser.id == parser.id.lower()
    assert parser.name and parser.version.count(".") == 2
    assert parser.file_types and all(t.startswith(".") for t in parser.file_types)


@pytest.mark.parametrize(("parser_id", "seed", "rows"), _cases())
def test_detect_matrix(parser_id: str, seed: int, rows: int) -> None:
    """Own fixture ≥ 0.8; other specific parsers < 0.5; and the registry picks the owner."""
    data, _ = fixture(parser_id, seed, rows)
    everyone = ParserRegistry.of([a.parser for a in adapters()])
    with open_document(data) as doc:
        own = _parser(parser_id).detect(doc)
        assert own >= 0.8, f"{parser_id} scored {own} on its own fixture"
        for other in adapters():
            if other.parser.id == parser_id or is_fallback(other.parser):
                continue  # fallbacks may match anything; ranking below keeps them out
            score = other.parser.detect(doc)
            assert score < 0.5, f"{other.parser.id} scored {score} on {parser_id}'s fixture"
        detection = everyone.detect(doc)
    assert detection.chosen is not None and detection.chosen.parser_id == parser_id


@pytest.mark.parametrize(("parser_id", "seed", "rows"), _cases())
def test_exact_parse(parser_id: str, seed: int, rows: int) -> None:
    data, expected = fixture(parser_id, seed, rows)
    with open_document(data) as doc:
        parsed = _parser(parser_id).parse(doc, None)
    assert parsed.transactions == expected.transactions
    assert parsed == expected


@pytest.mark.parametrize(("parser_id", "seed", "rows"), _cases())
def test_reconciles(parser_id: str, seed: int, rows: int) -> None:
    data, _ = fixture(parser_id, seed, rows)
    with open_document(data) as doc:
        parsed = _parser(parser_id).parse(doc, None)
    result = reconcile(
        parsed.balance_kind,
        parsed.opening_balance,
        parsed.closing_balance,
        [
            ReconRow(i, t.direction, t.amount, t.balance_after)
            for i, t in enumerate(parsed.transactions)
        ],
    )
    assert result.status == "ok", result
    assert result.first_break_seq is None


@pytest.mark.parametrize(("parser_id", "seed", "rows"), _cases())
def test_invariants(parser_id: str, seed: int, rows: int) -> None:
    data, _ = fixture(parser_id, seed, rows)
    with open_document(data) as doc:
        parsed = _parser(parser_id).parse(doc, None)
    assert parsed.account_hint is None or (
        parsed.account_hint.isdigit() and len(parsed.account_hint) <= 4
    )
    for txn in parsed.transactions:
        assert txn.amount > 0 and txn.amount.as_tuple().exponent == -2
        assert txn.direction in ("debit", "credit")
        assert txn.description.strip()
        if parsed.period_start and parsed.period_end:
            assert parsed.period_start <= txn.date <= parsed.period_end
    dates: list[date] = [t.date for t in parsed.transactions]
    assert dates == sorted(dates), "transactions must be in date order"


@pytest.mark.parametrize("parser_id", _ids())
def test_encrypted_fixture(parser_id: str) -> None:
    adapter = next(a for a in adapters() if a.parser.id == parser_id)
    data, expected = adapter.builder.build(11, 15, encrypted_with=PASSWORD)
    with pytest.raises(PasswordRequired) as no_password:
        open_document(data)
    assert not isinstance(no_password.value, WrongPassword)
    with pytest.raises(WrongPassword):
        open_document(data, password="not-it")
    with open_document(data, password=PASSWORD) as doc:
        assert doc.encrypted
        assert adapter.parser.detect(doc) >= 0.8
        assert adapter.parser.parse(doc, None) == expected


@pytest.mark.parametrize("parser_id", _ids())
def test_deterministic(parser_id: str) -> None:
    adapter = next(a for a in adapters() if a.parser.id == parser_id)
    first_bytes, first_expected = adapter.builder.build(8, 20)
    second_bytes, second_expected = adapter.builder.build(8, 20)
    assert first_bytes == second_bytes
    assert first_expected == second_expected
    results = []
    for _ in range(2):
        with open_document(first_bytes) as doc:
            results.append((adapter.parser.detect(doc), adapter.parser.parse(doc, None)))
    assert results[0] == results[1]
