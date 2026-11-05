"""The AI libraries are an optional extra (ADR-0030 §6): the app must start without them."""

import subprocess
import sys

BLOCK_AND_START = """
import importlib.abc, sys

class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in {"fastembed", "langchain_core", "langgraph",
                                  "langchain_google_genai", "langchain_ollama", "sqlglot"}:
            raise ImportError(f"blocked: {name}")
        return None

sys.meta_path.insert(0, Block())
from finboard.core.config import Settings
from finboard.main import create_app
from finboard.services.ai import extra_installed
create_app(Settings())
print("started")
"""


def test_app_starts_without_the_ai_extra() -> None:
    done = subprocess.run(  # noqa: S603  (a constant script, our own interpreter)
        [sys.executable, "-c", BLOCK_AND_START], capture_output=True, text=True, timeout=120
    )
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().endswith("started")
