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


def _rec(cid: str, start: int, end: int, page: int | None = 1, doc: int = 1, section: str | None = None):  # type: ignore[no-untyped-def]
    from citewell.models import ChunkRecord

    return ChunkRecord(
        chunk_id=cid,
        collection="c",
        document_id=doc,
        source="a.pdf",
        title=None,
        ord=0,
        page=page,
        section=section,
        char_start=start,
        char_end=end,
        text="x",
    )


def test_overlaps() -> None:
    from citewell.search import overlaps

    assert overlaps(_rec("a", 0, 100), _rec("b", 20, 90))  # b inside a
    assert overlaps(_rec("a", 0, 100), _rec("b", 40, 140))  # 60 of 100 shared
    assert not overlaps(_rec("a", 0, 100), _rec("b", 80, 180))  # 20 shared
    assert not overlaps(_rec("a", 0, 100), _rec("b", 0, 100, page=2))
    assert not overlaps(_rec("a", 0, 100), _rec("b", 0, 100, doc=2))
    assert not overlaps(_rec("a", 0, 100, page=None, section="A"), _rec("b", 0, 100, page=None, section="B"))


def test_select_diverse_skips_near_duplicates_and_backfills() -> None:
    from citewell.search import select_diverse

    records = {
        "a": _rec("a", 0, 300),
        "b": _rec("b", 0, 120),  # repeats a
        "c": _rec("c", 0, 300, page=2),
        "d": _rec("d", 0, 300, page=3),
    }
    ranked = [("a", 0.9), ("b", 0.8), ("c", 0.7), ("d", 0.6)]
    assert [cid for cid, _ in select_diverse(ranked, records, 3)] == ["a", "c", "d"]
    assert [cid for cid, _ in select_diverse(ranked, records, 1)] == ["a"]
