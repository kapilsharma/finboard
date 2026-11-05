"""Optional AI features (ARCHITECTURE §18, ADR-0030). Off by default.

Importing this package forces LangChain/LangSmith tracing off, whatever the environment
says: a trace would contain prompts and graph state, and would ship them to a third party
behind the one-outbound-module rule's back (ADR-0030 §4).
"""

import os

_TRACING_OFF = {
    "LANGSMITH_TRACING": "false",
    "LANGSMITH_TRACING_V2": "false",
    "LANGCHAIN_TRACING_V2": "false",
    "LANGCHAIN_TRACING": "false",
}
_TRACING_SECRETS = (
    "LANGSMITH_API_KEY",
    "LANGCHAIN_API_KEY",
    "LANGSMITH_ENDPOINT",
    "LANGCHAIN_ENDPOINT",
    "LANGSMITH_PROJECT",
    "LANGCHAIN_PROJECT",
)


def force_tracing_off() -> None:
    os.environ.update(_TRACING_OFF)
    for name in _TRACING_SECRETS:
        os.environ.pop(name, None)


force_tracing_off()
