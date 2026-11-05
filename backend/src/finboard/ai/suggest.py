"""Category suggestions from nearest neighbours (ARCHITECTURE §18, M3a). Pure.

Given the k nearest categorised transactions to one under review (by embedding cosine or
trigram similarity), each neighbour votes for its category with weight similarity**sharpness.
Categories are ranked by their share of the total weight; the top 3 whose share reaches a
floor are suggested, each with its closest examples as the "why".

Sharpness differs per method because the similarity scales differ: the
scales of cosine and trigram similarity differ. The values were tuned on one evaluation
seed and checked on four others (docs/ai-eval.md).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

K = 10
MAX_SUGGESTIONS = 3
CONFIDENCE_FLOOR = 0.2
MAX_EXAMPLES = 3
# Tuned per method by `finboard ai eval-suggestions` (docs/ai-eval.md); a unit test keeps
# these equal to what the evaluation picks.
SHARPNESS = {"trigram": 3.0, "embedding": 3.0}


@dataclass(frozen=True, slots=True)
class Neighbour:
    txn_id: uuid.UUID
    category_id: uuid.UUID
    similarity: float  # 0..1, higher is closer


@dataclass
class Suggestion:
    category_id: uuid.UUID
    confidence: float  # share of the neighbours' total weight, 0..1
    examples: list[Neighbour] = field(default_factory=list)


def vote(
    neighbours: list[Neighbour],
    *,
    sharpness: float = 1.0,
    min_similarity: float = 0.0,
    floor: float = CONFIDENCE_FLOOR,
    limit: int = MAX_SUGGESTIONS,
) -> list[Suggestion]:
    """Similarity-weighted vote. Neighbours below `min_similarity` don't vote at all, so a
    transaction like nothing seen before gets no suggestion rather than a weak guess."""
    usable = [n for n in neighbours if n.similarity >= min_similarity and n.similarity > 0]
    total = sum(n.similarity**sharpness for n in usable)
    if total <= 0:
        return []
    weights: dict[uuid.UUID, float] = defaultdict(float)
    examples: dict[uuid.UUID, list[Neighbour]] = defaultdict(list)
    for n in sorted(usable, key=lambda n: -n.similarity):
        weights[n.category_id] += n.similarity**sharpness
        if len(examples[n.category_id]) < MAX_EXAMPLES:
            examples[n.category_id].append(n)
    ranked = sorted(weights.items(), key=lambda kv: (-kv[1], str(kv[0])))
    return [
        Suggestion(cid, round(w / total, 3), examples[cid])
        for cid, w in ranked[:limit]
        if w / total >= floor
    ]
