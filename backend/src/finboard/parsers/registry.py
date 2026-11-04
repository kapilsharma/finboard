"""Parser discovery and detection (ADR-0009, ADR-0033).

Every parser — built-in or third-party — comes from the `finboard.parsers` entry-point group.
A parser that fails to load, targets another API version or reuses an id is left out and listed
in `failures` with a reason; it never stops the app from starting.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import entry_points

import structlog

from finboard.parsers.sdk import PARSER_API_VERSION, OpenedDocument, StatementParser

log = structlog.get_logger(__name__)

ENTRY_POINT_GROUP = "finboard.parsers"
FIXTURE_ENTRY_POINT_GROUP = "finboard.parser_fixtures"

DETECT_THRESHOLD = 0.5
AMBIGUITY_MARGIN = 0.1
PREFERRED_BONUS = 0.1  # the account's usual parser
_REQUIRED = ("id", "name", "version", "api_version", "detect", "parse", "file_types")


@dataclass(frozen=True, slots=True)
class LoadFailure:
    source: str  # "name = module:attr"
    reason: str


@dataclass(frozen=True, slots=True)
class Candidate:
    parser_id: str
    name: str
    confidence: float
    fallback: bool


@dataclass(frozen=True, slots=True)
class Detection:
    candidates: list[Candidate]  # best first
    chosen: Candidate | None
    ambiguous: bool  # top two specific parsers within AMBIGUITY_MARGIN: the user should check


def is_fallback(parser: StatementParser) -> bool:
    return bool(getattr(parser, "fallback", False))


def _instantiate(obj: object) -> object:
    # An entry point may name a parser instance, a class or a zero-argument factory.
    if isinstance(obj, type) or (callable(obj) and not hasattr(obj, "detect")):
        return obj()
    return obj


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers: dict[str, StatementParser] = {}
        self.failures: list[LoadFailure] = []

    # ---------------------------------------------------------------- loading

    @classmethod
    def from_entry_points(cls, extra: Iterable[str] = ()) -> ParserRegistry:
        """Load every installed parser. `extra` adds `module:attr` specs (tests, local dev)."""
        registry = cls()
        for ep in sorted(entry_points(group=ENTRY_POINT_GROUP), key=lambda e: e.name):
            source = f"{ep.name} = {ep.value}"
            try:
                loaded = ep.load()
            except Exception as exc:
                registry._fail(source, f"import failed: {type(exc).__name__}: {exc}")
                continue
            registry._register(source, loaded)
        for spec in extra:
            try:
                module_name, _, attr = spec.partition(":")
                loaded = getattr(importlib.import_module(module_name), attr)
            except Exception as exc:
                registry._fail(spec, f"import failed: {type(exc).__name__}: {exc}")
                continue
            registry._register(spec, loaded)
        return registry

    @classmethod
    def of(cls, parsers: Iterable[StatementParser]) -> ParserRegistry:
        """A registry over explicit parser objects (tests)."""
        registry = cls()
        for parser in parsers:
            registry._register(repr(parser), parser)
        return registry

    def _fail(self, source: str, reason: str) -> None:
        log.warning("parsers.load_failed", source=source, reason=reason)
        self.failures.append(LoadFailure(source=source, reason=reason))

    def _register(self, source: str, loaded: object) -> None:
        try:
            parser = _instantiate(loaded)
        except Exception as exc:
            self._fail(source, f"factory failed: {type(exc).__name__}: {exc}")
            return
        missing = [name for name in _REQUIRED if not hasattr(parser, name)]
        if missing:
            self._fail(source, f"not a parser: missing {', '.join(missing)}")
            return
        assert isinstance(parser, StatementParser)
        if parser.api_version != PARSER_API_VERSION:
            self._fail(
                source,
                f"built for parser API {parser.api_version}, this Finboard supports "
                f"{PARSER_API_VERSION}",
            )
            return
        if parser.id in self._parsers:
            self._fail(source, f"duplicate parser id '{parser.id}'")
            return
        self._parsers[parser.id] = parser

    # ---------------------------------------------------------------- queries

    def all(self) -> list[StatementParser]:
        return sorted(self._parsers.values(), key=lambda p: (is_fallback(p), p.id))

    def get(self, parser_id: str) -> StatementParser | None:
        return self._parsers.get(parser_id)

    def __contains__(self, parser_id: object) -> bool:
        return parser_id in self._parsers

    def detect(
        self,
        doc: OpenedDocument,
        *,
        file_type: str = ".pdf",
        preferred_id: str | None = None,
        enabled: Sequence[str] | None = None,
    ) -> Detection:
        """Score every enabled parser for this file type and pick one.

        Bank-specific parsers at or above the threshold win over fallbacks; a fallback is
        chosen only when no specific parser recognises the file.
        """
        candidates: list[Candidate] = []
        for parser in self.all():
            if enabled is not None and parser.id not in enabled:
                continue
            if file_type not in parser.file_types:
                continue
            try:
                score = float(parser.detect(doc))
            except Exception as exc:  # detect must never raise; treat a bug as "not mine"
                log.warning("parsers.detect_failed", parser_id=parser.id, error=type(exc).__name__)
                score = 0.0
            score = max(0.0, min(1.0, score))
            if parser.id == preferred_id and score > 0:
                score = min(1.0, score + PREFERRED_BONUS)
            candidates.append(
                Candidate(parser.id, parser.name, round(score, 3), is_fallback(parser))
            )

        candidates.sort(key=lambda c: (-c.confidence, c.fallback, c.parser_id))
        specific = [c for c in candidates if not c.fallback and c.confidence >= DETECT_THRESHOLD]
        fallbacks = [c for c in candidates if c.fallback and c.confidence >= DETECT_THRESHOLD]
        chosen = specific[0] if specific else (fallbacks[0] if fallbacks else None)
        ambiguous = (
            len(specific) >= 2
            and specific[0].confidence - specific[1].confidence < AMBIGUITY_MARGIN
        )
        return Detection(candidates=candidates, chosen=chosen, ambiguous=ambiguous)


@lru_cache
def default_registry(extra: tuple[str, ...] = ()) -> ParserRegistry:
    """The process-wide registry (parsers are global; enablement is per user)."""
    return ParserRegistry.from_entry_points(extra)
