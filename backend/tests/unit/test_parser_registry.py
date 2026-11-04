"""Registry rules (ADR-0009, ADR-0033): failures are isolated and listed, ranking prefers
bank-specific parsers over fallbacks, and detect bugs don't break detection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from finboard.parsers.registry import ParserRegistry
from finboard.parsers.sdk import (
    PARSER_API_VERSION,
    OpenedDocument,
    ParsedStatement,
    ParsedTransaction,
    ParserError,
)
from finboard.parsers.sdk.helpers import last_digits, parse_amount, parse_date, parse_signed_amount


@dataclass
class FakeParser:
    id: str
    score: float = 0.0
    fallback: bool = False
    api_version: int = PARSER_API_VERSION
    name: str = "Fake"
    version: str = "1.0.0"
    file_types: tuple[str, ...] = (".pdf",)
    institutions: tuple[str, ...] = ()
    account_types: tuple[str, ...] = ()
    options_schema: None = None
    explode: bool = False

    def detect(self, doc: OpenedDocument) -> float:
        if self.explode:
            raise RuntimeError("bug in detect")
        return self.score

    def parse(self, doc: OpenedDocument, options: object) -> ParsedStatement:
        raise ParserError("not used")


DOC = OpenedDocument(file_name="x.pdf", sha256="0" * 64, kind="pdf", pdf=None)


def registry(*parsers: FakeParser) -> ParserRegistry:
    return ParserRegistry.of(parsers)  # type: ignore[arg-type]


def test_api_version_mismatch_and_duplicates_are_listed_not_fatal() -> None:
    reg = registry(
        FakeParser("ok"),
        FakeParser("old", api_version=0),
        FakeParser("ok"),
        object(),  # type: ignore[arg-type]
    )
    assert [p.id for p in reg.all()] == ["ok"]
    reasons = [f.reason for f in reg.failures]
    assert any("parser API 0" in r for r in reasons)
    assert any("duplicate parser id 'ok'" in r for r in reasons)
    assert any("not a parser" in r for r in reasons)


def test_unimportable_extra_parser_is_a_failure() -> None:
    reg = ParserRegistry.from_entry_points(extra=("finboard.nope:Parser",))
    assert "generic_table" in reg
    assert reg.failures[-1].source == "finboard.nope:Parser"
    assert "import failed" in reg.failures[-1].reason


def test_specific_parser_beats_higher_scoring_fallback() -> None:
    detection = registry(FakeParser("generic", 0.9, fallback=True), FakeParser("bank", 0.6)).detect(
        DOC
    )
    assert detection.chosen is not None and detection.chosen.parser_id == "bank"
    assert [c.parser_id for c in detection.candidates] == ["generic", "bank"]


def test_fallback_only_when_nothing_specific() -> None:
    detection = registry(FakeParser("generic", 0.8, fallback=True), FakeParser("bank", 0.3)).detect(
        DOC
    )
    assert detection.chosen is not None and detection.chosen.parser_id == "generic"


def test_nothing_above_threshold() -> None:
    assert registry(FakeParser("bank", 0.49)).detect(DOC).chosen is None


def test_close_scores_are_ambiguous_and_preferred_gets_a_bonus() -> None:
    reg = registry(FakeParser("a", 0.80), FakeParser("b", 0.75))
    assert reg.detect(DOC).ambiguous
    preferred = reg.detect(DOC, preferred_id="b")
    assert preferred.chosen is not None and preferred.chosen.parser_id == "b"


def test_detect_exceptions_count_as_zero() -> None:
    detection = registry(FakeParser("buggy", explode=True), FakeParser("ok", 0.7)).detect(DOC)
    assert detection.chosen is not None and detection.chosen.parser_id == "ok"


def test_disabled_and_wrong_file_type_are_skipped() -> None:
    reg = registry(FakeParser("a", 0.9), FakeParser("csv", 0.9, file_types=(".csv",)))
    assert reg.detect(DOC, enabled=[]).candidates == []
    assert [c.parser_id for c in reg.detect(DOC).candidates] == ["a"]


# ---------------------------------------------------------------- SDK model + helpers


def test_parsed_transaction_rejects_bad_money() -> None:
    with pytest.raises(ParserError):
        ParsedTransaction(date(2026, 1, 1), "x", Decimal("1.5"), "debit")
    with pytest.raises(ParserError):
        ParsedTransaction(date(2026, 1, 1), "x", Decimal("0.00"), "debit")
    with pytest.raises(ParserError):
        ParsedTransaction(date(2026, 1, 1), "x", 1.50, "debit")  # type: ignore[arg-type]


def test_parsed_statement_rejects_long_account_hint() -> None:
    with pytest.raises(ParserError, match="account_hint"):
        ParsedStatement("Bank", "asset", [], account_hint="123456")


def test_sdk_helpers() -> None:
    assert parse_amount("INR 1,23,456.7") == Decimal("123456.70")
    assert parse_amount("-5.00") is None
    assert parse_signed_amount("1,000.00 Cr") == (Decimal("1000.00"), "cr")
    assert parse_signed_amount("-12.00") == (Decimal("12.00"), "dr")
    assert parse_date("05-Sep-2026") == date(2026, 9, 5)
    assert parse_date("05/09/26") == date(2026, 9, 5)
    assert parse_date("not a date") is None
    assert last_digits("XXXX XXXX 1234") == "1234"
    assert last_digits("XX12") is None
