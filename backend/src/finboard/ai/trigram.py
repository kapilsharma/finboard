"""Trigram similarity, the same as Postgres `pg_trgm`'s `similarity()` (M3a baseline).

Words are runs of letters and digits, lower-cased, padded with two spaces in front and one
behind; similarity is |shared trigrams| / |all trigrams|. Keeping this identical to
pg_trgm means the offline evaluation measures exactly what the database runs.
"""

from __future__ import annotations

import re
from functools import lru_cache

_WORD = re.compile(r"[^\W_]+")


@lru_cache(maxsize=65536)
def trigrams(text: str) -> frozenset[str]:
    grams: set[str] = set()
    for word in _WORD.findall(text.lower()):
        padded = f"  {word} "
        grams.update(padded[i : i + 3] for i in range(len(padded) - 2))
    return frozenset(grams)


def similarity(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)
