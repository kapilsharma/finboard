#!/usr/bin/env python3
"""Print one version's section of CHANGELOG.md (the release notes for that tag).

    python scripts/changelog_section.py 1.0.0

Exits 1 when the version has no section, so a release can't go out without notes.
"""

import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


def section(text: str, version: str) -> str | None:
    heading = re.compile(r"^## \[?([^\]\s]+)\]?.*$", re.MULTILINE)
    matches = list(heading.finditer(text))
    for index, match in enumerate(matches):
        if match.group(1) == version:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            return text[match.end() : end].strip()
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    version = argv[0].removeprefix("v")
    body = section(CHANGELOG.read_text(encoding="utf-8"), version)
    if not body:
        print(f"CHANGELOG.md has no section for {version}.", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
