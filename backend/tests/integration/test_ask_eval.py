"""`finboard ai eval` harness: with an oracle model (it answers each golden question with its
reference) every question scores, which proves the references and the scoring both work."""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.ai.llm import LlmReply, LlmRequest
from finboard.core.config import Settings
from finboard.services.ai import AiConfig
from finboard.services.ask_eval import load_golden, report, run_eval, same_rows, write_section


class Oracle:
    model = "oracle"

    def __init__(self, wrong: set[str] = frozenset()) -> None:  # type: ignore[assignment]
        _, golden = load_golden()
        self.golden = {g.question: g for g in golden}
        self.wrong = wrong

    async def complete(self, request: LlmRequest) -> LlmReply:
        g = self.golden[request.question]
        if request.question in self.wrong:
            return LlmReply(json.dumps({"kind": "spec", "spec": {"metric": "income"}}))
        if request.task == "understand":
            reply = {"kind": "spec", "spec": g.spec} if g.spec else {"kind": "sql"}
        else:
            reply = {"sql": g.sql}
        return LlmReply(json.dumps(reply), 50, 10)


async def test_oracle_scores_every_question(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, tmp_path: Path
) -> None:
    _, golden = load_golden()
    assert len(golden) >= 30
    config = AiConfig.from_settings(
        settings.model_copy(update={"ai_ask": "gemini", "ai_ask_sql": True})
    )
    wrong = {golden[1].question}
    outcomes = await run_eval(sessionmaker, config, lambda: Oracle(wrong), delay=0)
    assert [o.question for o in outcomes if not o.correct] == [golden[1].question]
    assert {o.path for o in outcomes} == {"spec", "sql"}

    text = report(outcomes, model="oracle", ask_sql=True)
    assert f"Execution accuracy: {len(golden) - 1}/{len(golden)}" in text
    out = tmp_path / "ai-eval.md"
    out.write_text("# Category suggestion evaluation (M3a)\n\nkept\n")
    write_section(out, text)
    write_section(out, text)  # replaces its own section, keeps the rest
    content = out.read_text()
    assert content.startswith("# Category suggestion evaluation (M3a)\n\nkept\n")
    assert content.count("<!-- ask-eval:start -->") == 1


def test_same_rows_ignores_order_and_types() -> None:
    assert same_rows([("A", 1), ("B", "2.50")], [("2.5", "b"), (1, "a")])
    assert not same_rows([("A", 1)], [("A", 2)])
