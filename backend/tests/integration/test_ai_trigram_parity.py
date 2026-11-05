"""The offline evaluation's trigram similarity is exactly what pg_trgm computes."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from finboard.ai import evaluation
from finboard.ai.trigram import similarity


async def test_python_trigram_matches_pg_trgm(owner_engine: AsyncEngine) -> None:
    labelled, queries = evaluation.dataset(11)
    pairs = [(q.text, e.text) for q, e in zip(queries[:60], labelled * 2, strict=False)]
    pairs += [("A-1 b_2", "a 1 b 2"), ("ÉCOLE café", "ecole cafe"), ("", "x")]
    async with owner_engine.connect() as conn:
        for a, b in pairs:
            db = (await conn.execute(text("SELECT similarity(:a, :b)"), {"a": a, "b": b})).scalar()
            assert round(float(db), 4) == round(similarity(a, b), 4), (a, b)
