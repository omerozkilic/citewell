"""Model wrappers tested with a fake ``sentence_transformers`` module (no downloads)."""

import sys
import types

import numpy as np
import pytest

from citewell.embeddings import SentenceTransformerEmbedder, build_embedder
from citewell.rerank import CrossEncoderReranker, build_reranker


class _FakeST:
    def __init__(self, name: str, device: str | None = None) -> None:
        self.name = name
        self.max_seq_length = 0
        self.seen: list[str] = []

    def get_sentence_embedding_dimension(self) -> int:
        return 4

    def encode(self, texts: list[str], **_: object) -> np.ndarray:
        self.seen.extend(texts)
        return np.ones((len(texts), 4), dtype=np.float32) / 2


class _FakeCE:
    def __init__(self, name: str, device: str | None = None, max_length: int = 512) -> None:
        self.name = name

    def predict(self, pairs: list[tuple[str, str]], **_: object) -> list[float]:
        return [float(len(p)) - 3 for _, p in pairs]


@pytest.fixture
def fake_st(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = types.ModuleType("sentence_transformers")
    mod.SentenceTransformer = _FakeST  # type: ignore[attr-defined]
    mod.CrossEncoder = _FakeCE  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", mod)


def test_e5_prefixes(fake_st: None) -> None:
    e = SentenceTransformerEmbedder("intfloat/multilingual-e5-large", dim=4)
    e.embed_documents(["belge"])
    e.embed_query("soru")
    seen = e._model.seen
    assert seen == ["passage: belge", "query: soru"]
    assert e.embed_documents([]).shape == (0, 4)


def test_bge_has_no_prefix_and_dim_check(fake_st: None) -> None:
    e = build_embedder("sentence-transformers", "BAAI/bge-m3", 4)
    assert e.embed_query("soru").shape == (4,)
    with pytest.raises(ValueError, match="CITEWELL_EMBEDDING_DIM"):
        SentenceTransformerEmbedder("BAAI/bge-m3", dim=1024)


def test_cross_encoder_sigmoid(fake_st: None) -> None:
    r = build_reranker("sentence-transformers", "BAAI/bge-reranker-v2-m3")
    assert isinstance(r, CrossEncoderReranker)
    scores = r.score("q", ["abc", "abcdefgh"])
    assert scores[0] == pytest.approx(0.5)
    assert 0.5 < scores[1] < 1.0
    assert r.score("q", []) == []
