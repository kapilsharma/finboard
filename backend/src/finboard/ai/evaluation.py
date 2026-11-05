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

        q, t = unit(embed(queries)), unit(embed(labelled))
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
    sims = matrix([q.text for q in queries], [e.text for e in labelled])
    correct = covered = covered_correct = 0
    per_variant: dict[str, list[int]] = {}
    for query, row in zip(queries, sims, strict=True):
        candidates = [
            Neighbour(ids[i], categories[labelled[i].category], s)
            for i, s in enumerate(row)
            if labelled[i].direction == query.direction
        ]
        nearest = sorted(candidates, key=lambda n: -n.similarity)[:K]
        top = vote(nearest, sharpness=sharpness, floor=0.0)
        shown = vote(nearest, sharpness=sharpness, min_similarity=min_similarity)
        ok = bool(top) and names[top[0].category_id] == query.category
        correct += ok
        per_variant.setdefault(query.variant, []).append(int(ok))
        if shown:
            covered += 1
            covered_correct += names[shown[0].category_id] == query.category
    n = len(queries)
    return Score(
        method=method,
        top1=round(correct / n, 3),
        covered=round(covered / n, 3),
        precision_covered=round(covered_correct / covered, 3) if covered else 0.0,
        by_variant={k: round(sum(v) / len(v), 3) for k, v in sorted(per_variant.items())},
        queries=n,
    )


# ---------------------------------------------------------------- the report (docs/ai-eval.md)

TUNING_SEED = 7
HELD_OUT_SEEDS = (11, 23, 41, 97)
SHARPNESS_GRID = (1, 2, 3, 4, 6, 8, 12, 16, 24)


@dataclass(frozen=True, slots=True)
class MethodResult:
    method: str
    sharpness: float
    tuning: float
    held_out: dict[int, Score]

    @property
    def mean(self) -> float:
        return round(sum(s.top1 for s in self.held_out.values()) / len(self.held_out), 3)


def compare(methods: dict[str, Similarity]) -> list[MethodResult]:
    """Tune each method's sharpness on one seed, then score it on the held-out seeds."""
    results = []
    for name, matrix in methods.items():
        tuning = {p: evaluate(name, matrix, TUNING_SEED, sharpness=p).top1 for p in SHARPNESS_GRID}
        best = max(tuning, key=lambda p: (tuning[p], -p))
        held = {s: evaluate(name, matrix, s, sharpness=best) for s in HELD_OUT_SEEDS}
        results.append(MethodResult(name, best, tuning[best], held))
    return results


def report(results: list[MethodResult], *, baseline: str = "trigram") -> str:
    base = next(r for r in results if r.method == baseline)
    winner = max(results, key=lambda r: r.mean)
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
    verdict = (
        f"**{winner.method}** wins ({winner.mean:.3f} vs the {baseline} baseline's "
        f"{base.mean:.3f}), "
        "so suggestions use embeddings when the model is available."
        if winner.method != baseline
        else f"The {baseline} baseline wins, so suggestions use it (embeddings don't beat it)."
    )
    lines += ["", "## Verdict", "", verdict, ""]
    return "\n".join(lines)
