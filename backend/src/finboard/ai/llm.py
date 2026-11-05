"""The only code that talks to an LLM provider (ADR-0030 §4).

What can leave the machine is fixed by `LlmRequest`, a typed allow-list: the question, the
catalog (names and descriptions), the user's category paths, account aliases (type and bank,
never the display name), today's date, and on a retry a locally written hint. `render()` is
the one function that turns it into provider messages; a canary test runs the real
LangChain client against a fake chat model and checks no data value ever appears.

Provider failures map to `AiUnavailable` (429 and timeouts as "try again shortly"). Provider
error text is never logged or shown: it can echo the prompt.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from finboard.domain.errors import AiUnavailable

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


class AccountAlias(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    alias: str = Field(pattern=r"^Account [A-Z0-9]+$")
    type: str
    bank: str | None = None

    def line(self) -> str:
        bank = f", {self.bank}" if self.bank else ""
        return f"{self.alias} — {self.type.replace('_', ' ')}{bank}"


class LlmRequest(BaseModel):
    """Everything a prompt may contain. Nothing else is accepted (`extra="forbid"`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task: Literal["understand", "generate_sql"]
    question: str = Field(max_length=500)
    catalog: str
    category_paths: list[str]
    accounts: list[AccountAlias]
    today: date
    allow_sql: bool = False
    retry_hint: str | None = Field(default=None, max_length=300)  # written locally


@dataclass(frozen=True, slots=True)
class LlmReply:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class LlmClient(Protocol):
    model: str

    async def complete(self, request: LlmRequest) -> LlmReply: ...


_SPEC_SCHEMA = """{"kind": "spec", "spec": {
  "metric": "spending" | "income" | "invested" | "net" | "count",
  "categories": [category paths from the list],
  "accounts": [account aliases from the list],
  "merchant": text to match in the merchant, or null,
  "start": "YYYY-MM-DD" or null, "end": "YYYY-MM-DD" or null,
  "last_months": N (this month and the N-1 before it) or null,
  "group_by": up to two of "month", "category", "account", "merchant",
  "top": N or null,
  "chart": "bar" | "grouped_bar" | "line" | "table" or null}}"""

_UNDERSTAND = """You turn questions about a person's own spending into a query spec for Finboard.
Reply with one JSON object and nothing else, one of:
{spec_schema}
{sql_option}{{"kind": "clarify", "question": a short clarifying question}}
Map everyday words to the listed categories (for example "eating out" may be "Dining out",
"provisions" may be "Groceries"). Spending means expense categories; transfers never count.
Use only listed category paths and account aliases."""

_GENERATE = """You write one PostgreSQL SELECT that answers a question about a person's own
transactions, using only the tables below. Reply with one JSON object and nothing else:
{{"sql": "...", "chart": "bar" | "grouped_bar" | "line" | "table" | null}}"""


def render(request: LlmRequest) -> list[tuple[str, str]]:
    """The provider messages: (role, text). The only place a prompt is built."""
    if request.task == "understand":
        sql_option = (
            '{"kind": "sql", "reason": why a spec cannot express it}\n' if request.allow_sql else ""
        )
        system = _UNDERSTAND.format(spec_schema=_SPEC_SCHEMA, sql_option=sql_option)
    else:
        system = _GENERATE.format()
    context = [
        f"Today is {request.today.isoformat()}.",
        "Categories:\n" + "\n".join(f"- {p}" for p in request.category_paths),
        "Accounts:\n" + "\n".join(f"- {a.line()}" for a in request.accounts),
    ]
    if request.task == "generate_sql":
        context.insert(0, request.catalog)
    human = "\n\n".join([*context, f"Question: {request.question}"])
    if request.retry_hint:
        human += f"\n\nYour previous reply could not be used: {request.retry_hint}. Try again."
    return [("system", system), ("human", human)]


_JSON = re.compile(r"\{.*\}", re.DOTALL)


def parse_json(text: str) -> dict[str, Any]:
    """The first JSON object in a reply (models sometimes wrap it in a code fence)."""
    match = _JSON.search(text)
    if not match:
        raise ValueError("the reply was not a JSON object")
    value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("the reply was not a JSON object")
    return value


class LangChainClient:
    """Any LangChain chat model: Gemini by default, Ollama as the local option."""

    def __init__(self, chat: BaseChatModel, *, model: str, timeout: float) -> None:
        self.chat = chat
        self.model = model
        self.timeout = timeout

    async def complete(self, request: LlmRequest) -> LlmReply:
        messages = render(request)
        try:
            reply = await asyncio.wait_for(self.chat.ainvoke(messages), self.timeout)
        except TimeoutError:
            raise AiUnavailable(
                "The AI provider didn't answer in time; try again shortly"
            ) from None
        except Exception as exc:  # provider SDKs raise their own types
            raise _unavailable(exc) from None
        content = reply.content
        text = (
            content
            if isinstance(content, str)
            else "".join(
                part if isinstance(part, str) else str(part.get("text", "")) for part in content
            )
        )
        usage: dict[str, Any] = getattr(reply, "usage_metadata", None) or {}
        return LlmReply(text, int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)))


def _unavailable(exc: Exception) -> AiUnavailable:
    name = type(exc).__name__
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if code == 429 or "ResourceExhausted" in name or "RateLimit" in name or "429" in str(code):
        return AiUnavailable("The AI provider is busy (rate limit); try again shortly")
    if "Timeout" in name:
        return AiUnavailable("The AI provider didn't answer in time; try again shortly")
    return AiUnavailable(f"The AI provider couldn't answer ({name})")


def make_client(
    provider: Literal["gemini", "ollama"],
    *,
    model: str,
    timeout: float,
    gemini_api_key: str | None = None,
    ollama_url: str | None = None,
) -> LlmClient:
    if provider == "gemini":
        if not gemini_api_key:
            raise AiUnavailable("FINBOARD_GEMINI_API_KEY isn't set")
        from langchain_google_genai import ChatGoogleGenerativeAI

        chat: BaseChatModel = ChatGoogleGenerativeAI(
            model=model, google_api_key=gemini_api_key, temperature=0, max_retries=0,
            timeout=timeout,
        )  # fmt: skip
    else:
        from langchain_ollama import ChatOllama

        chat = ChatOllama(model=model, base_url=ollama_url, temperature=0, format="json")
    return LangChainClient(chat, model=model, timeout=timeout)
