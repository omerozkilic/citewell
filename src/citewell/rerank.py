"""Optional cross-encoder reranking (default model: BAAI/bge-reranker-v2-m3)."""

from __future__ import annotations

import logging
import math
import threading
from typing import Protocol, runtime_checkable

from citewell.embeddings import load_cached_first
from citewell.text import tokenize

log = logging.getLogger(__name__)


@runtime_checkable
class Reranker(Protocol):
    name: str

    def score(self, query: str, passages: list[str]) -> list[float]: ...


class CrossEncoderReranker:
    def __init__(self, model_name: str, device: str | None = None, max_length: int = 512):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:  # pragma: no cover - optional extra
            raise RuntimeError("Reranking needs the 'models' extra: pip install 'citewell[models]'") from exc
        log.info("loading reranker %s", model_name)
        self._model = load_cached_first(CrossEncoder, model_name, device=device, max_length=max_length)
        self.name = model_name
        self._lock = threading.Lock()

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        with self._lock:
            raw = self._model.predict([(query, p) for p in passages], show_progress_bar=False)
        # Map logits to (0, 1) so scores are comparable across queries.
        return [1.0 / (1.0 + math.exp(-float(x))) for x in raw]


class LexicalOverlapReranker:
    """Tiny dependency-free reranker used in tests: fraction of query tokens present."""

    name = "lexical-overlap"

    def score(self, query: str, passages: list[str]) -> list[float]:
        q = {t[:5] for t in tokenize(query) if len(t) > 1}
        if not q:
            return [0.0] * len(passages)
        out = []
        for p in passages:
            toks = {t[:5] for t in tokenize(p)}
            out.append(len(q & toks) / len(q))
        return out


def build_reranker(backend: str, model_name: str, device: str | None = None) -> Reranker | None:
    if backend == "none":
        return None
    if backend == "lexical":
        return LexicalOverlapReranker()
    if backend == "sentence-transformers":
        return CrossEncoderReranker(model_name, device=device)
    raise ValueError(f"unknown reranker backend: {backend}")
