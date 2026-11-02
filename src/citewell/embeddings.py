"""Embedding backends.

* ``sentence-transformers`` – real local models (bge-m3, multilingual-e5, …).
  Requires the ``models`` extra. Runs fully offline once the model is cached.
* ``hash`` – deterministic character n-gram feature hashing. It is *not* a
  semantic model; it exists so that tests, CI and "does the plumbing work?"
  checks run in milliseconds without downloading anything.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Protocol, runtime_checkable

import numpy as np
import numpy.typing as npt

from citewell.text import tokenize

log = logging.getLogger(__name__)

Vector = npt.NDArray[np.float32]


@runtime_checkable
class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> Vector: ...

    def embed_query(self, text: str) -> Vector: ...


def _l2_normalise(m: Vector) -> Vector:
    norms = np.linalg.norm(m, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    out: Vector = (m / norms).astype(np.float32)
    return out


class HashEmbedder:
    """Character n-gram hashing embedder (lexical, deterministic, dependency-free)."""

    def __init__(self, dim: int = 1024, ngram: tuple[int, int] = (3, 5), language: str = "turkish"):
        self.dim = dim
        self.ngram = ngram
        self.language = language
        self.name = f"hash-{dim}"

    def _vec(self, text: str) -> Vector:
        v = np.zeros(self.dim, dtype=np.float32)
        for token in tokenize(text, self.language):
            padded = f"<{token}>"
            for n in range(self.ngram[0], self.ngram[1] + 1):
                for i in range(max(1, len(padded) - n + 1)):
                    gram = padded[i : i + n]
                    h = int.from_bytes(hashlib.blake2b(gram.encode(), digest_size=8).digest(), "little")
                    v[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        return v

    def embed_documents(self, texts: list[str]) -> Vector:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return _l2_normalise(np.stack([self._vec(t) for t in texts]))

    def embed_query(self, text: str) -> Vector:
        vec: Vector = self.embed_documents([text])[0]
        return vec


class SentenceTransformerEmbedder:
    """Wraps a ``sentence_transformers.SentenceTransformer`` model.

    E5-family models expect ``query: `` / ``passage: `` prefixes; they are added
    automatically when the model name contains ``e5``.
    """

    def __init__(
        self,
        model_name: str,
        dim: int | None = None,
        device: str | None = None,
        batch_size: int = 16,
        max_seq_length: int = 512,
    ):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError(
                "The sentence-transformers backend needs the 'models' extra: "
                "pip install 'citewell[models]' (or set CITEWELL_EMBEDDING_BACKEND=hash for testing)."
            ) from exc
        log.info("loading embedding model %s", model_name)
        self._model = SentenceTransformer(model_name, device=device)
        self._model.max_seq_length = max_seq_length
        self.name = model_name
        actual = int(self._model.get_sentence_embedding_dimension() or 0)
        if dim is not None and actual and actual != dim:
            raise ValueError(
                f"{model_name} produces {actual}-d vectors but CITEWELL_EMBEDDING_DIM={dim}. "
                "Set CITEWELL_EMBEDDING_DIM to match the model (it is fixed per database)."
            )
        self.dim = actual or (dim or 0)
        self.batch_size = batch_size
        lowered = model_name.lower()
        self._q_prefix, self._d_prefix = ("query: ", "passage: ") if "e5" in lowered else ("", "")
        self._lock = threading.Lock()

    def _encode(self, texts: list[str]) -> Vector:
        with self._lock:  # torch models are not re-entrant across threads
            out = self._model.encode(
                texts,
                batch_size=self.batch_size,
                normalize_embeddings=True,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
        vecs: Vector = np.asarray(out, dtype=np.float32)
        return vecs

    def embed_documents(self, texts: list[str]) -> Vector:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return self._encode([self._d_prefix + t for t in texts])

    def embed_query(self, text: str) -> Vector:
        vec: Vector = self._encode([self._q_prefix + text])[0]
        return vec


def build_embedder(
    backend: str,
    model_name: str,
    dim: int,
    device: str | None = None,
    batch_size: int = 16,
    max_seq_length: int = 512,
) -> Embedder:
    if backend == "hash":
        return HashEmbedder(dim=dim)
    if backend == "sentence-transformers":
        return SentenceTransformerEmbedder(
            model_name, dim=dim, device=device, batch_size=batch_size, max_seq_length=max_seq_length
        )
    raise ValueError(f"unknown embedding backend: {backend}")
