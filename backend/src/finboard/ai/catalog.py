"""The query catalog (`catalog.yaml`): table and column descriptions for prompts. Versioned."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

import yaml


@dataclass(frozen=True, slots=True)
class Catalog:
    version: int
    tables: dict[str, dict[str, str]]  # table -> column -> type
    text: str  # what goes in the prompt

    def columns(self, table: str) -> dict[str, str]:
        return self.tables[table]


@cache
def load() -> Catalog:
    raw: dict[str, Any] = yaml.safe_load(
        resources.files("finboard.ai").joinpath("catalog.yaml").read_text(encoding="utf-8")
    )
    tables = {
        name: {col: str(spec["type"]) for col, spec in t["columns"].items()}
        for name, t in raw["tables"].items()
    }
    lines: list[str] = []
    for name, t in raw["tables"].items():
        lines.append(f"TABLE {name}: {' '.join(str(t['description']).split())}")
        for col, spec in t["columns"].items():
            lines.append(f"  {col} ({spec['type']}): {spec['description']}")
    lines.append("METRICS:")
    lines.extend(f"  {k}: {v}" for k, v in raw["metrics"].items())
    lines.append("RULES:")
    lines.extend(f"  - {r}" for r in raw["rules"])
    return Catalog(version=int(raw["version"]), tables=tables, text="\n".join(lines))
