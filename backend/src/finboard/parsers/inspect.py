"""`finboard inspect-layout`: a statement's *structure* with its contents masked.

Every digit becomes `9` and every letter becomes `X`; punctuation, spacing and positions are
kept. That is enough to build a parser and a synthetic fixture for a bank's layout, and safe to
share: no account numbers, names, descriptions, dates or amounts survive.
"""

import re

from finboard.parsers.sdk import OpenedDocument

_DIGIT = re.compile(r"\d")
_LETTER = re.compile(r"[^\W\d_]")


def mask(text: str) -> str:
    return _LETTER.sub("X", _DIGIT.sub("9", text))


def inspect_layout(doc: OpenedDocument, *, tables: bool = True) -> str:
    """Positions are in PDF points from the page's top-left corner."""
    if doc.pdf is None:
        return "(not a PDF)"
    out: list[str] = [f"pages: {doc.pdf.page_count}  encrypted: {'yes' if doc.encrypted else 'no'}"]
    for index in range(doc.pdf.page_count):
        page = doc.pdf.page(index)
        out.append("")
        out.append(f"=== page {index + 1} ({float(page.width):.0f} x {float(page.height):.0f} pt)")
        out.append("--- text lines: top | x0-x1 word ...")
        for line in doc.pdf.lines(index):
            words = "  ".join(f"[{w.x0:.0f}-{w.x1:.0f}] {mask(w.text)}" for w in line.words)
            out.append(f"{line.top:7.1f} | {words}")
        if tables:
            for t_index, table in enumerate(doc.pdf.tables(index), start=1):
                out.append(f"--- table {t_index}: {len(table)} rows")
                for row in table:
                    out.append(" | ".join(mask(cell or "").replace("\n", " / ") for cell in row))
    return "\n".join(out)
