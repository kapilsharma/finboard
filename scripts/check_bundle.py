#!/usr/bin/env python3
"""Fail if the built SPA would make the browser contact another host (ARCHITECTURE §13).

    python scripts/check_bundle.py backend/src/finboard/web/static

Finboard bundles every asset: no CDNs, web fonts or analytics. This reads the build output and
refuses any absolute URL that isn't on the short list below. Those are identifiers and links
inside library code (XML namespaces, links printed in error messages), never fetched.
Standard library only: the image check runs it inside the container.
"""

import re
import sys
from pathlib import Path

# Hosts that may appear as text. Nothing is loaded from them.
TEXT_ONLY_HOSTS = {
    "www.w3.org",  # SVG / XLink / MathML namespaces
    "react.dev",  # React's "see https://react.dev/errors/NNN" messages
    "reactrouter.com",  # React Router's warning links
    "tanstack.com",  # TanStack Query's warning links
    "github.com",  # issue links in library warnings
    "localhost",  # `new URL(path, "http://localhost")` used to parse relative URLs
}
TEXT_SUFFIXES = {".html", ".js", ".mjs", ".css", ".svg", ".json", ".map", ".txt", ".webmanifest"}
URL = re.compile(r"""(?:https?:)?//([A-Za-z0-9.-]+\.[A-Za-z]{2,}|localhost)(?=[/:"'`)\s\\]|$)""")
# Tags and CSS that fetch: these must never point at another host, listed or not.
FETCHING = re.compile(
    r"""(?:\bsrc|\bhref|\baction)\s*=\s*["']?\s*(?:https?:)?//|url\(\s*["']?(?:https?:)?//|@import\s+["'](?:https?:)?//""",
    re.IGNORECASE,
)


def problems(root: Path) -> list[str]:
    found: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        name = path.relative_to(root).as_posix()
        if path.suffix.lower() in {".html", ".css"} and FETCHING.search(text):
            found.append(f"{name}: loads something from another host")
        for match in URL.finditer(text):
            # `//` also starts comments and appears in regexes; only count real schemes there.
            if not match.group(0).startswith("http") and path.suffix.lower() != ".html":
                continue
            host = match.group(1).lower()
            if host not in TEXT_ONLY_HOSTS:
                found.append(f"{name}: {host}")
    return sorted(set(found))


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    root = Path(argv[0])
    if not (root / "index.html").is_file():
        print(f"No built SPA in {root} (index.html is missing).", file=sys.stderr)
        return 2
    bad = problems(root)
    if bad:
        print("The bundle refers to hosts that aren't allow-listed:", file=sys.stderr)
        for line in bad:
            print(f"  {line}", file=sys.stderr)
        return 1
    print(f"Bundle is self-contained ({root}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
