"""Public parser SDK (ARCHITECTURE §8). Adapters import from here and nowhere else in finboard.

`PARSER_API_VERSION` is bumped only for incompatible changes; the registry refuses parsers built
for another version (ADR-0009). `finboard.parsers.sdk.testing` holds the fixture-builder kit and
is only needed by tests.
"""

from finboard.parsers.sdk.document import (
    DocumentError,
    OpenedDocument,
    PasswordRequired,
    PdfView,
    TextLine,
    Word,
    WrongPassword,
    is_pdf,
    open_document,
    pdf_needs_password,
)
from finboard.parsers.sdk.model import (
    PARSER_API_VERSION,
    AccountTypeName,
    BalanceKind,
    Direction,
    ParsedStatement,
    ParsedTransaction,
    ParserError,
    StatementParser,
)

__all__ = [
    "PARSER_API_VERSION",
    "AccountTypeName",
    "BalanceKind",
    "Direction",
    "DocumentError",
    "OpenedDocument",
    "ParsedStatement",
    "ParsedTransaction",
    "ParserError",
    "PasswordRequired",
    "PdfView",
    "StatementParser",
    "TextLine",
    "Word",
    "WrongPassword",
    "is_pdf",
    "open_document",
    "pdf_needs_password",
]
