"""Helpers for the Ask Finboard tests: a scripted model (recorded replies, no network) that
keeps every request it was sent, and an app with Ask available."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from finboard.ai.llm import LlmReply, LlmRequest, render
from finboard.auth import Principal
from finboard.core.config import Settings
from finboard.main import create_app

from .conftest import HeaderAuthBackend, RecordingJobQueue

API = "/api/v1"


@dataclass
class ScriptedLlm:
    """Replies in order; records the rendered messages of every request."""

    replies: list[str] = field(default_factory=list)
    requests: list[LlmRequest] = field(default_factory=list)
    model: str = "scripted"

    async def complete(self, request: LlmRequest) -> LlmReply:
        self.requests.append(request)
        if not self.replies:
            raise AssertionError("the model was asked more often than scripted")
        return LlmReply(self.replies.pop(0), tokens_in=100, tokens_out=20)

    def sent(self) -> str:
        """Everything that would have left the machine."""
        return "\n".join(text for r in self.requests for _, text in render(r))


def spec_reply(**spec: Any) -> str:
    return json.dumps({"kind": "spec", "spec": spec})


def sql_reply(sql: str, chart: str | None = None) -> str:
    return "```json\n" + json.dumps({"sql": sql, "chart": chart}) + "\n```"


@pytest.fixture
def llm() -> ScriptedLlm:
    return ScriptedLlm()


@pytest.fixture
async def ask_app(
    settings: Settings,
    alice: Principal,
    bob: Principal,
    job_queue: RecordingJobQueue,
    llm: ScriptedLlm,
) -> AsyncIterator[FastAPI]:
    ai = settings.model_copy(update={"ai_ask": "gemini", "ai_ask_sql": True})
    backend = HeaderAuthBackend({"alice": alice, "bob": bob}, default="alice")
    application = create_app(ai, auth_backend=backend, job_queue=job_queue, llm_factory=lambda: llm)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def ask_client(ask_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ask_app),
        base_url="http://127.0.0.1",
        headers={"X-Finboard-Client": "1"},
    ) as c:
        for user in ("alice", "bob"):
            on = await c.patch(
                f"{API}/ai/settings", json={"ask": True}, headers={"X-Test-User": user}
            )
            assert on.status_code == 200, on.text
        yield c
