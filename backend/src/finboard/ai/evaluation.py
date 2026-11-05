"""Suggestion evaluation (M3a, ARCHITECTURE §18): embeddings vs the trigram baseline.

The question is whether embeddings find the right category for descriptions that rules would
miss: the same merchant written differently. So the test data is generated:

* a **labelled set**: each synthetic merchant appears a few times, in real narration formats
  (UPI, POS, NEFT, ECS), as the user's already-categorised transactions;
* **queries**: variants of the same merchants that a rule wouldn't match exactly: typos,
  other UPI handles and banks, truncation (POS terminals cut names short), reordered or
  extra tokens, spaces dropped. Any query whose normalised text equals a labelled one is
  excluded: exact repeats are what rules already catch.

Each method ranks the labelled set by similarity to a query (same direction only), the k
nearest vote (`ai.suggest.vote`), and the top-1 category is compared with the truth. All
synthetic: no real merchant data, deterministic for a seed.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from finboard.ai.suggest import K, Neighbour, vote
from finboard.ai.text import match_text
from finboard.ai.trigram import similarity as trigram_similarity
from finboard.categorisation.normalise import normalise

# Synthetic merchants by category (common Indian merchant styles; made up or generic).
MERCHANTS: dict[str, list[str]] = {
    "Dining out": [
        "SWIGGY",
        "ZOMATO",
        "DOMINOS PIZZA",
        "BURGER SINGH",
        "CHAAYOS CAFE",
        "HALDIRAMS",
        "BARBEQUE NATION",
        "THIRD WAVE COFFEE",
    ],
    "Groceries": [
        "BIGBASKET",
        "DMART AVENUE",
        "BLINKIT",
        "ZEPTO MARKETPLACE",
        "RELIANCE FRESH",
        "NATURES BASKET",
        "MORE RETAIL",
        "SPENCERS RETAIL",
    ],
    "Transport": [
        "UBER INDIA",
        "OLA CABS",
        "RAPIDO BIKE",
        "IRCTC TICKETING",
        "HPCL PETROL PUMP",
        "INDIAN OIL FUEL",
        "NAMMA METRO",
        "REDBUS INDIA",
    ],
    "Shopping": [
        "AMAZON SELLER SERVICES",
        "FLIPKART INTERNET",
        "MYNTRA DESIGNS",
        "AJIO RELIANCE",
        "NYKAA FASHION",
        "DECATHLON SPORTS",
        "CROMA ELECTRONICS",
        "IKEA INDIA",
    ],
    "Utilities": [
        "AIRTEL POSTPAID",
        "JIO PREPAID",
        "BESCOM ELECTRICITY",
        "MAHANAGAR GAS",
        "TATA PLAY DTH",
        "ACT FIBERNET",
        "BWSSB WATER",
        "VODAFONE IDEA",
    ],
    "Health": [
        "APOLLO PHARMACY",
        "PHARMEASY",
        "TATA 1MG",
        "MEDPLUS HEALTH",
        "PRACTO TECHNOLOGIES",
        "CULT FIT",
        "MANIPAL HOSPITAL",
        "THYROCARE LABS",
    ],
    "Entertainment": [
        "NETFLIX COM",
        "SPOTIFY INDIA",
        "BOOKMYSHOW",
        "PVR CINEMAS",
        "DISNEY HOTSTAR",
        "SONYLIV",
        "STEAM GAMES",
        "AUDIBLE INDIA",
    ],
    "Salary": [
        "ACME TECH PVT LTD",
        "GLOBEX SOLUTIONS",
        "INITECH SOFTWARE",
        "UMBRELLA LABS",
        "STARK INDUSTRIES INDIA",
        "WAYNE ENTERPRISES",
        "HOOLI INDIA",
        "PIED PIPER TECH",
    ],
}
CREDIT_CATEGORIES = {"Salary"}
# Merchants the user has never categorised: the right answer is no suggestion. Without
# these the evaluation can't tell how high the "too different to vote" cut-off should be.
UNSEEN_MERCHANTS = [
    "KALYAN SWEETS", "RAJU AUTO PARTS", "LAKSHMI TAILORS", "GREEN LEAF SALON",
    "SHARMA HARDWARE", "MEHTA OPTICALS", "BLUE DART COURIER", "SUNRISE DENTAL CLINIC",
    "PATEL STATIONERY", "CITY PARKING", "NIRMAL DRY CLEANERS", "OM PET CARE",
    "VIJAY FURNITURE", "ROYAL ENFIELD SERVICE", "ANAND BOOK DEPOT", "KAVERI LAUNDRY",
]  # fmt: skip
BANKS = ["YESB", "HDFC", "ICIC", "SBIN", "UTIB", "KKBK"]
PSPS = ["ybl", "okaxis", "okhdfcbank", "paytm", "okicici", "ibl"]
CITIES = ["BANGALORE", "MUMBAI", "PUNE", "DELHI", "CHENNAI", "HYDERABAD"]
NOTES = ["PAYMENT", "ORDER", "UPI", "BILL", "COLLECT"]


@dataclass(frozen=True, slots=True)
class Example:
    text: str  # normalised description
    category: str
    direction: str
    merchant: str
    variant: str = "labelled"


def _ref(rng: random.Random, digits: int = 12) -> str:
    return "".join(rng.choice("0123456789") for _ in range(digits))


def narration(rng: random.Random, merchant: str, direction: str, style: str) -> str:
    """A raw bank narration for a merchant, in one of the common formats."""
    handle = merchant.split()[0].lower()
    if direction == "credit":
        return {
            "neft": f"NEFT-HDFCN{_ref(rng, 14)}-{merchant}-SALARY",
            "imps": f"IMPS/{_ref(rng)}/{merchant}/SAL",
            "upi": f"NEFT CR {merchant} SALARY {_ref(rng, 6)}",
        }.get(style, f"NEFT CR {merchant}")
    return {
        "upi": (
            f"UPI/DR/{_ref(rng)}/{merchant}/{rng.choice(BANKS)}/"
            f"{handle}@{rng.choice(PSPS)}/{rng.choice(NOTES)}"
        ),
        "pos": f"POS {_ref(rng, 4)}XXXXXXXX{_ref(rng, 4)} {merchant} {rng.choice(CITIES)}",
        "neft": f"ECS/{merchant}/{_ref(rng, 8)}",
    }.get(style, merchant)


def _typo(rng: random.Random, word: str) -> str:
    if len(word) < 4:
        return word
    i = rng.randrange(1, len(word) - 1)
    kind = rng.choice(["swap", "drop", "double"])
    if kind == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2 :]
    if kind == "drop":
        return word[:i] + word[i + 1 :]
    return word[:i] + word[i] + word[i:]


def variants(rng: random.Random, merchant: str) -> dict[str, str]:
    """Ways the same merchant shows up that an exact rule would miss."""
    words = merchant.split()
    longest = max(range(len(words)), key=lambda i: len(words[i]))
    typo = list(words)
    typo[longest] = _typo(rng, words[longest])
    out = {
        "typo": " ".join(typo),
        "truncated": merchant.replace(" ", "")[: max(5, len(merchant.replace(" ", "")) * 2 // 3)],
        "no_spaces": merchant.replace(" ", ""),
        "reordered": " ".join(reversed(words))
        if len(words) > 1
        else f"{merchant} {rng.choice(CITIES)}",
        "extra_tokens": (
            f"{merchant} {rng.choice(CITIES)} {rng.choice(['ONLINE', 'STORE', 'PVT', 'INDIA'])}"
        ),
        "other_handle": merchant,  # same name, different handle, bank and note below
    }
    return out


def dataset(seed: int = 7, labelled_per_merchant: int = 3) -> tuple[list[Example], list[Example]]:
    rng = random.Random(seed)  # noqa: S311 (synthetic data)
    labelled: list[Example] = []
    for category, merchants in MERCHANTS.items():
        direction = "credit" if category in CREDIT_CATEGORIES else "debit"
        styles = ["neft", "imps", "upi"] if direction == "credit" else ["upi", "pos", "neft"]
        for merchant in merchants:
            for style in styles[:labelled_per_merchant]:
                text = normalise(narration(rng, merchant, direction, style))
                labelled.append(Example(text, category, direction, merchant))
    known = {e.text for e in labelled}
    queries: list[Example] = []
    for category, merchants in MERCHANTS.items():
        direction = "credit" if category in CREDIT_CATEGORIES else "debit"
        for merchant in merchants:
            for kind, name in variants(rng, merchant).items():
                style = rng.choice(["upi", "pos"] if direction == "debit" else ["neft", "imps"])
                text = normalise(narration(rng, name, direction, style))
                if text and text not in known:
                    queries.append(Example(text, category, direction, merchant, kind))
    return labelled, queries


def unseen(seed: int = 7) -> list[Example]:
    """Narrations of never-categorised merchants (their own random stream, so adding them
    leaves `dataset()` unchanged)."""
    rng = random.Random(seed * 7919 + 1)  # noqa: S311 (synthetic data)
    return [
        Example(
            normalise(narration(rng, merchant, "debit", style)), "", "debit", merchant, "unseen"
        )
        for merchant in UNSEEN_MERCHANTS
        for style in ("upi", "pos")
    ]


Similarity = Callable[[Sequence[str], Sequence[str]], list[list[float]]]


def trigram_matrix(queries: Sequence[str], labelled: Sequence[str]) -> list[list[float]]:
    return [[trigram_similarity(q, t) for t in labelled] for q in queries]


def embedding_matrix_for(embed: Callable[[Sequence[str]], list[list[float]]]) -> Similarity:
    """Cosine similarity via an embedding function (vectors normalised here)."""

    def matrix(queries: Sequence[str], labelled: Sequence[str]) -> list[list[float]]:
        import numpy as np

        def unit(rows: list[list[float]]) -> Any:
            array = np.asarray(rows, dtype=np.float32)
            return array / np.linalg.norm(array, axis=1, keepdims=True)

        def texts(rows: Sequence[str]) -> list[str]:  # what production embeds
            return [match_text(r) or r for r in rows]

        q, t = unit(embed(texts(queries))), unit(embed(texts(labelled)))
        result: list[list[float]] = (q @ t.T).clip(0, 1).tolist()
        return result

    return matrix


@dataclass(frozen=True, slots=True)
class Score:
    method: str
    top1: float  # accuracy of the top suggestion
    covered: float  # share of queries that get any suggestion above the floor
    precision_covered: float  # accuracy when a suggestion is shown
    by_variant: dict[str, float]
    queries: int
    unseen_suggested: float = 0.0  # share of never-seen merchants given a suggestion (wrong)
    utility: float = 0.0  # per query: +1 right suggestion, -1 wrong or on an unseen merchant


_SIMS: dict[tuple[int, int], tuple[list[list[float]], list[list[float]]]] = {}


def _similarities(matrix: Similarity, seed: int) -> tuple[list[list[float]], list[list[float]]]:
    """(queries x labelled, unseen x labelled), computed once per matrix and seed."""
    key = (id(matrix), seed)
    if key not in _SIMS:
        labelled, queries = dataset(seed)
        texts = [e.text for e in labelled]
        _SIMS[key] = (
            matrix([q.text for q in queries], texts),
            matrix([q.text for q in unseen(seed)], texts),
        )
    return _SIMS[key]


def evaluate(
    method: str,
    matrix: Similarity,
    seed: int = 7,
    *,
    sharpness: float = 1.0,
    min_similarity: float = 0.0,
) -> Score:
    labelled, queries = dataset(seed)
    ids = [uuid.UUID(int=i + 1) for i in range(len(labelled))]
    categories = {c: uuid.uuid5(uuid.NAMESPACE_URL, c) for c in MERCHANTS}
    names = {v: k for k, v in categories.items()}
    sims, unseen_sims = _similarities(matrix, seed)

    def nearest(query: Example, row: list[float]) -> list[Neighbour]:
        candidates = [
            Neighbour(ids[i], categories[labelled[i].category], s)
            for i, s in enumerate(row)
            if labelled[i].direction == query.direction
        ]
        return sorted(candidates, key=lambda n: -n.similarity)[:K]

    correct = covered = covered_correct = 0
    per_variant: dict[str, list[int]] = {}
    for query, row in zip(queries, sims, strict=True):
        near = nearest(query, row)
        top = vote(near, sharpness=sharpness, floor=0.0)
        shown = vote(near, sharpness=sharpness, min_similarity=min_similarity)
        ok = bool(top) and names[top[0].category_id] == query.category
        correct += ok
        per_variant.setdefault(query.variant, []).append(int(ok))
        if shown:
            covered += 1
            covered_correct += names[shown[0].category_id] == query.category
    negatives = unseen(seed)
    wrongly_shown = sum(
        bool(vote(nearest(q, row), sharpness=sharpness, min_similarity=min_similarity))
        for q, row in zip(negatives, unseen_sims, strict=True)
    )
    n = len(queries)
    utility = (2 * covered_correct - covered - wrongly_shown) / (n + len(negatives))
    return Score(
        method=method,
        top1=round(correct / n, 3),
        covered=round(covered / n, 3),
        precision_covered=round(covered_correct / covered, 3) if covered else 0.0,
        by_variant={k: round(sum(v) / len(v), 3) for k, v in sorted(per_variant.items())},
        queries=n,
        unseen_suggested=round(wrongly_shown / len(negatives), 3),
        utility=round(utility, 3),
    )


# ---------------------------------------------------------------- the report (docs/ai-eval.md)

TUNING_SEED = 7
HELD_OUT_SEEDS = (11, 23, 41, 97)
SHARPNESS_GRID = (1, 2, 3, 4, 6, 8, 12, 16, 24)
THRESHOLD_GRID = tuple(round(0.05 * i, 2) for i in range(0, 19))  # 0.00 .. 0.90


@dataclass(frozen=True, slots=True)
class MethodResult:
    method: str
    sharpness: float
    tuning: float
    held_out: dict[int, Score]
    min_similarity: float = 0.0

    @property
    def mean(self) -> float:
        return round(sum(s.top1 for s in self.held_out.values()) / len(self.held_out), 3)


def compare(methods: dict[str, Similarity]) -> list[MethodResult]:
    """Tune each method's sharpness on one seed, then score it on the held-out seeds."""
    results = []
    for name, matrix in methods.items():
        tuning = {p: evaluate(name, matrix, TUNING_SEED, sharpness=p).top1 for p in SHARPNESS_GRID}
        best = max(tuning, key=lambda p: (tuning[p], -p))
        # Then the cut-off below which a neighbour doesn't vote, by utility on the same seed.
        utility = {
            t: evaluate(name, matrix, TUNING_SEED, sharpness=best, min_similarity=t).utility
            for t in THRESHOLD_GRID
        }
        cut = max(utility, key=lambda t: (utility[t], -t))
        held = {
            s: evaluate(name, matrix, s, sharpness=best, min_similarity=cut) for s in HELD_OUT_SEEDS
        }
        results.append(MethodResult(name, best, tuning[best], held, cut))
    return results


NOISE = 0.01  # held-out means closer than this are within seed-to-seed variation


def report(
    results: list[MethodResult],
    *,
    baseline: str = "trigram",
    default: str = "sentence-transformers/all-MiniLM-L6-v2",
) -> str:
    base = next(r for r in results if r.method == baseline)
    winner = max(results, key=lambda r: r.mean)
    chosen = next((r for r in results if r.method == default), winner)
    lines = [
        "# Category suggestion evaluation (M3a)",
        "",
        "Generated by `finboard ai eval-suggestions` (ARCHITECTURE §18,",
        "`finboard/ai/evaluation.py`).",
        "Synthetic merchants only. Queries are variants a rule would miss (typos, other UPI",
        "handles and banks, truncation, reordered or extra tokens, spaces dropped); exact repeats",
        "of a labelled description are excluded. Each method's vote sharpness is tuned on seed",
        f"{TUNING_SEED} and scored on seeds {', '.join(map(str, HELD_OUT_SEEDS))},",
        "which it never saw.",
        "",
        "## Top-1 accuracy on held-out seeds",
        "",
        "| Method | Sharpness | " + " | ".join(f"Seed {s}" for s in HELD_OUT_SEEDS) + " | Mean |",
        "|---|---|" + "---|" * len(HELD_OUT_SEEDS) + "---|",
    ]
    for r in results:
        cells = " | ".join(f"{r.held_out[s].top1:.3f}" for s in HELD_OUT_SEEDS)
        lines.append(f"| {r.method} | {r.sharpness:g} | {cells} | **{r.mean:.3f}** |")
    lines += [
        "",
        "## When a suggestion is shown (held-out mean)",
        "",
        "Neighbours less similar than the cut-off don't vote, so a transaction unlike anything",
        "categorised gets no suggestion. The cut-off is tuned on seed "
        f"{TUNING_SEED} for utility (+1 right suggestion, -1 wrong one, -1 any suggestion for one",
        f"of {len(UNSEEN_MERCHANTS)} never-categorised merchants, 0 no suggestion).",
        "",
        "| Method | Cut-off | Shown | Right when shown | Unseen merchants given one | Utility |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        n = len(r.held_out)
        mean = {
            f: sum(float(getattr(s, f)) for s in r.held_out.values()) / n
            for f in ("covered", "precision_covered", "unseen_suggested", "utility")
        }
        lines.append(
            f"| {r.method} | {r.min_similarity:.2f} | {mean['covered']:.3f} | "
            f"{mean['precision_covered']:.3f} | {mean['unseen_suggested']:.3f} | "
            f"{mean['utility']:.3f} |"
        )
    lines += ["", "## By kind of variant (mean over held-out seeds)", ""]
    kinds = sorted(next(iter(results[0].held_out.values())).by_variant)
    lines.append("| Method | " + " | ".join(kinds) + " |")
    lines.append("|---|" + "---|" * len(kinds))
    for r in results:
        avg = {
            k: sum(s.by_variant.get(k, 0) for s in r.held_out.values()) / len(r.held_out)
            for k in kinds
        }
        lines.append(f"| {r.method} | " + " | ".join(f"{avg[k]:.3f}" for k in kinds) + " |")
    if winner.method == baseline:
        verdict = f"The {baseline} baseline wins, so suggestions use it (embeddings don't beat it)."
    else:
        verdict = (
            f"Embeddings beat the {baseline} baseline ({base.mean:.3f}), so suggestions use "
            f"them when the model is available. The default, **{chosen.method}**, scores "
            f"{chosen.mean:.3f}"
        )
        if chosen.method == winner.method:
            verdict += ", the best here."
        elif winner.mean - chosen.mean < NOISE:
            verdict += (
                f"; {winner.method} scores {winner.mean:.3f}, within seed-to-seed noise "
                f"(< {NOISE}), so the default stays."
            )
        else:
            verdict += f"; **{winner.method}** scores {winner.mean:.3f}: consider switching."
    lines += ["", "## Verdict", "", verdict, ""]
    return "\n".join(lines)
