import numpy as np
import pytest

from citewell.embeddings import HashEmbedder, build_embedder
from citewell.fusion import reciprocal_rank_fusion
from citewell.rerank import LexicalOverlapReranker, build_reranker


def test_rrf_basic() -> None:
    fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "d"]], k=60)
    ids = [i for i, _ in fused]
    assert ids[:2] == ["b", "c"]  # present in both lists
    assert set(ids) == {"a", "b", "c", "d"}
    assert fused[0][1] == pytest.approx(1 / 62 + 1 / 61)


def test_rrf_ties_are_deterministic() -> None:
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "a"]])
    assert [i for i, _ in fused] == ["a", "b"]


def test_rrf_weights() -> None:
    fused = reciprocal_rank_fusion([["a"], ["b"]], weights=[1.0, 2.0])
    assert fused[0][0] == "b"
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], weights=[1.0, 2.0])


def test_rrf_empty() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


def test_hash_embedder_deterministic_and_normalised() -> None:
    e = HashEmbedder(dim=128)
    a = e.embed_documents(["yıllık izin süresi", "parola uzunluğu"])
    b = e.embed_documents(["yıllık izin süresi", "parola uzunluğu"])
    assert a.shape == (2, 128)
    assert np.allclose(a, b)
    assert np.allclose(np.linalg.norm(a, axis=1), 1.0)
    q = e.embed_query("izin günleri")
    assert float(q @ a[0]) > float(q @ a[1])
    assert e.embed_documents([]).shape == (0, 128)


def test_hash_embedder_turkish_case_insensitive() -> None:
    e = HashEmbedder(dim=64)
    assert np.allclose(e.embed_query("IŞIK"), e.embed_query("ışık"))


def test_build_embedder_unknown() -> None:
    with pytest.raises(ValueError):
        build_embedder("nope", "x", 8)


def test_lexical_reranker() -> None:
    r = LexicalOverlapReranker()
    scores = r.score("yıllık izin", ["yıllık izin 14 gün", "parola", ""])
    assert scores[0] == 1.0 and scores[1] == 0.0
    assert r.score("", ["x"]) == [0.0]


def test_build_reranker() -> None:
    assert build_reranker("none", "x") is None
    assert isinstance(build_reranker("lexical", "x"), LexicalOverlapReranker)
    with pytest.raises(ValueError):
        build_reranker("nope", "x")
