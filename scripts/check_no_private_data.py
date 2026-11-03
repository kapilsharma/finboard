#!/usr/bin/env python3
"""Fail if git tracks (or is about to commit) files that could hold real financial data.

Used by pre-commit and CI. Statements, databases, dumps and exports must never enter the repo;
test fixtures are generated at test time instead (docs/ARCHITECTURE.md §8, §13).

    python scripts/check_no_private_data.py            # check every tracked file
    python scripts/check_no_private_data.py FILE ...   # check given files (pre-commit)
"""

import subprocess
import sys
from pathlib import PurePosixPath

FORBIDDEN_SUFFIXES = {
    ".pdf", ".db", ".sqlite", ".sqlite3", ".sql", ".dump", ".zip", ".xls", ".xlsx", ".ofx", ".qif",
}
FORBIDDEN_NAMES = {".env"}
# Synthetic data shipped with the approved design handover.
ALLOWED_PREFIXES = ("docs/handover/design/",)


def violations(paths: list[str]) -> list[str]:
    bad = []
    for raw in paths:
        path = PurePosixPath(raw.replace("\\", "/"))
        if str(path).startswith(ALLOWED_PREFIXES):
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES or path.name in FORBIDDEN_NAMES:
            bad.append(str(path))
    return bad


def main(argv: list[str]) -> int:
    paths = argv or subprocess.run(
        ["git", "ls-files"], check=True, capture_output=True, text=True  # noqa: S607
    ).stdout.splitlines()
    bad = violations(paths)
    if bad:
        print("Refusing files that may contain private financial data:", file=sys.stderr)
        for path in bad:
            print(f"  {path}", file=sys.stderr)
        print("Statements and databases never belong in the repo. Generate fixtures in tests.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
