"""Text embeddings with fastembed (ONNX on CPU, no PyTorch), loaded once per process.

Runtime never downloads: models load with `local_files_only=True`. The one download is an
explicit `finboard ai fetch-model` (ADR-0030: no silent network calls). Needs the `ai` extra.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

DIMENSIONS = 384  # both all-MiniLM-L6-v2 and bge-small-en-v1.5


class EmbeddingsUnavailable(RuntimeError):
    """The `ai` extra isn't installed, or the model hasn't been fetched."""


def _fastembed() -> Any:
    try:
        import fastembed
    except ImportError:
        raise EmbeddingsUnavailable("Install the ai extra: uv sync --extra ai") from None
    return fastembed


def fetch(model: str, cache_dir: Path) -> Path:
    """Download the model into `cache_dir` (the only network call this module makes)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Plain HTTPS downloads; the Xet client needs extra hosts some networks block.
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    _fastembed().TextEmbedding(model, cache_dir=str(cache_dir))
    return cache_dir


@lru_cache(maxsize=2)
def _model(model: str, cache_dir: str) -> Any:
    os.environ["HF_HUB_OFFLINE"] = "1"  # belt and braces: never reach the network here
    try:
        return _fastembed().TextEmbedding(model, cache_dir=cache_dir, local_files_only=True)
    except EmbeddingsUnavailable:
        raise
    except Exception as exc:
        raise EmbeddingsUnavailable(
            "The embedding model isn't downloaded yet: run `finboard ai fetch-model` "
            f"({type(exc).__name__})"
        ) from None


def is_ready(model: str, cache_dir: Path) -> bool:
    try:
        _model(model, str(cache_dir))
    except EmbeddingsUnavailable:
        return False
    return True


def embed(
    texts: Sequence[str], *, model: str, cache_dir: Path, batch_size: int = 128
) -> list[list[float]]:
    """Unit-length vectors (cosine similarity = dot product)."""
    if not texts:
        return []
    import numpy as np

    vectors = np.asarray(
        list(_model(model, str(cache_dir)).embed(list(texts), batch_size=batch_size))
    )
    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    result: list[list[float]] = vectors.astype(float).tolist()
    return result
