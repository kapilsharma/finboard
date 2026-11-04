"""`OpenedDocument`: what a parser receives. Built once per import, after decryption.

Decryption happens here, in memory only (ADR-0027): the decrypted bytes are never written to
disk and never leave the worker process.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from types import TracebackType
from typing import TYPE_CHECKING, Any, Literal, Self

import pikepdf

from finboard.parsers.sdk.model import ParserError

if TYPE_CHECKING:
    from pdfplumber.page import Page
    from pdfplumber.pdf import PDF

PDF_MAGIC = b"%PDF-"


class DocumentError(ParserError):
    """The file can't be opened at all (not a PDF, corrupt, …)."""


class PasswordRequired(DocumentError):
    def __init__(self, user_message: str = "This statement is password-protected") -> None:
        super().__init__(user_message)


class WrongPassword(PasswordRequired):
    def __init__(self) -> None:
        super().__init__("That password didn't open the statement")


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float


@dataclass(frozen=True, slots=True)
class TextLine:
    page: int  # 0-based
    top: float
    words: tuple[Word, ...]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def x0(self) -> float:
        return self.words[0].x0

    @property
    def x1(self) -> float:
        return self.words[-1].x1


class PdfView:
    """Lazy access to the pages of a decrypted PDF. Results are cached per page."""

    LINE_TOLERANCE = 2.5  # points: words whose tops differ less than this share a line

    def __init__(self, data: bytes, page_count: int) -> None:
        self._data = data
        self.page_count = page_count
        self._pdf: PDF | None = None
        self._text: dict[int, str] = {}
        self._lines: dict[int, list[TextLine]] = {}

    @property
    def plumber(self) -> PDF:
        """The underlying pdfplumber document, for adapters that need more than text/lines."""
        if self._pdf is None:
            import pdfplumber

            self._pdf = pdfplumber.open(io.BytesIO(self._data))
        return self._pdf

    def page(self, index: int) -> Page:
        page: Page = self.plumber.pages[index]
        return page

    def page_text(self, index: int) -> str:
        if index not in self._text:
            self._text[index] = self.page(index).extract_text() or ""
        return self._text[index]

    def text(self, max_pages: int | None = None) -> str:
        count = self.page_count if max_pages is None else min(max_pages, self.page_count)
        return "\n".join(self.page_text(i) for i in range(count))

    def lines(self, index: int) -> list[TextLine]:
        """Words grouped into visual lines (top to bottom, words left to right)."""
        if index not in self._lines:
            words: list[dict[str, Any]] = self.page(index).extract_words(
                keep_blank_chars=False, use_text_flow=False
            )
            words.sort(key=lambda w: (round(float(w["top"]), 1), float(w["x0"])))
            lines: list[list[Word]] = []
            tops: list[float] = []
            for raw in words:
                word = Word(
                    text=str(raw["text"]),
                    x0=float(raw["x0"]),
                    x1=float(raw["x1"]),
                    top=float(raw["top"]),
                    bottom=float(raw["bottom"]),
                )
                if lines and abs(word.top - tops[-1]) <= self.LINE_TOLERANCE:
                    lines[-1].append(word)
                else:
                    lines.append([word])
                    tops.append(word.top)
            self._lines[index] = [
                TextLine(page=index, top=top, words=tuple(sorted(ws, key=lambda w: w.x0)))
                for top, ws in zip(tops, lines, strict=True)
            ]
        return self._lines[index]

    def all_lines(self) -> list[TextLine]:
        return [line for i in range(self.page_count) for line in self.lines(i)]

    def tables(self, index: int) -> list[list[list[str | None]]]:
        tables: list[list[list[str | None]]] = self.page(index).extract_tables()
        return tables

    def close(self) -> None:
        if self._pdf is not None:
            self._pdf.close()
            self._pdf = None


@dataclass(frozen=True)
class OpenedDocument:
    file_name: str
    sha256: str
    kind: Literal["pdf", "csv", "xlsx"]
    pdf: PdfView | None
    encrypted: bool = False
    tabular: None = field(default=None)  # CSV/XLS view: a later API version

    def close(self) -> None:
        if self.pdf is not None:
            self.pdf.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def is_pdf(data: bytes) -> bool:
    return data[:1024].lstrip().startswith(PDF_MAGIC)


def pdf_needs_password(data: bytes) -> bool:
    """True if the PDF can't be opened without a user password."""
    try:
        with pikepdf.open(io.BytesIO(data)):
            return False
    except pikepdf.PasswordError:
        return True
    except pikepdf.PdfError as exc:
        raise DocumentError("This file isn't a readable PDF") from exc


def open_document(
    data: bytes,
    *,
    file_name: str = "statement.pdf",
    password: str | None = None,
    max_pages: int | None = None,
) -> OpenedDocument:
    """Validate, decrypt (in memory) and wrap a statement for the parsers.

    Raises PasswordRequired (no password given), WrongPassword, or DocumentError.
    """
    if not is_pdf(data):
        raise DocumentError("Only PDF statements are supported")
    sha256 = hashlib.sha256(data).hexdigest()
    try:
        pdf = pikepdf.open(io.BytesIO(data), password=password or "")
    except pikepdf.PasswordError as exc:
        raise (WrongPassword() if password else PasswordRequired()) from exc
    except pikepdf.PdfError as exc:
        raise DocumentError("This file isn't a readable PDF") from exc

    with pdf:
        page_count = len(pdf.pages)
        if max_pages is not None and page_count > max_pages:
            raise DocumentError(f"The statement has more than {max_pages} pages")
        encrypted = bool(pdf.is_encrypted)
        if encrypted:
            out = io.BytesIO()
            pdf.save(out, encryption=False)  # decrypted copy, memory only
            plain = out.getvalue()
        else:
            plain = data
    return OpenedDocument(
        file_name=file_name,
        sha256=sha256,
        kind="pdf",
        pdf=PdfView(plain, page_count),
        encrypted=encrypted,
    )
