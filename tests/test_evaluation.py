import json
from pathlib import Path

import pytest

from citewell.evaluation import (
    EvalQuery,
    RelevantItem,
    RunConfig,
    load_dataset,
    percentile,
    report_markdown,
    run_eval,
    score_query,
)
from citewell.models import SearchHit, SearchResponse
from citewell.search import SearchRequest

from .conftest import EVAL_TR


def hit(rank: int, source: str, page: int | None = None) -> SearchHit:
    return SearchHit(
        rank=rank,
        score=1.0 / rank,
        chunk_id=f"c{rank}",
        collection="default",
        document_id=1,
        source=source,
        title=None,
        page=page,
        section=None,
        text="",
        quote="",
    )


def test_score_query_page_and_doc_level() -> None:
    q = EvalQuery(
        id="1", query="x", relevant=[RelevantItem(source="a.pdf", page=2), RelevantItem(source="b.md")]
    )
    hits = [hit(1, "a.pdf", 1), hit(2, "b.md"), hit(3, "a.pdf", 2)]
    first, recall, doc_hit, page_hit = score_query(q, hits, k=5)
    assert first == 2
    assert recall == 1.0
    assert doc_hit is True and page_hit is True

    first, recall, doc_hit, page_hit = score_query(q, hits, k=1)
    assert first is None and recall == 0.0
    assert doc_hit is True  # right document, wrong page
    assert page_hit is False


def test_score_query_without_pages() -> None:
    q = EvalQuery(id="1", query="x", relevant=[RelevantItem(source="b.md")])
    *_, page_hit = score_query(q, [hit(1, "b.md")], 5)
    assert page_hit is None


def test_percentile() -> None:
    assert percentile([], 50) == 0.0
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([5], 95) == 5


def test_run_config_parse() -> None:
    assert RunConfig.parse("hybrid+rerank") == RunConfig("hybrid", True)
    assert RunConfig.parse(" vector ").label == "vector"
    with pytest.raises(ValueError):
        RunConfig.parse("hybrid+magic")


def test_load_dataset(tmp_path: Path) -> None:
    qs = load_dataset(EVAL_TR)
    assert len(qs) >= 30
    assert all(q.relevant for q in qs)
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps({"id": "1", "query": "x", "relevant": []}) + "\n")
    with pytest.raises(ValueError, match=r"bad\.jsonl:1"):
        load_dataset(bad)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n// comment\n")
    with pytest.raises(ValueError, match="empty"):
        load_dataset(empty)


class FakeService:
    def __init__(self) -> None:
        self.calls: list[SearchRequest] = []

    def search(self, req: SearchRequest) -> SearchResponse:
        self.calls.append(req)
        hits = [hit(1, "a.pdf", 1), hit(2, "b.md")] if "a" in req.query else [hit(1, "z.md")]
        return SearchResponse(
            query=req.query, mode=req.mode, reranked=False, collections=[], took_ms=1, hits=hits
        )


def test_run_eval_metrics() -> None:
    queries = [
        EvalQuery(id="1", query="a", relevant=[RelevantItem(source="a.pdf", page=1)]),
        EvalQuery(id="2", query="a again", relevant=[RelevantItem(source="b.md")], collection="other"),
        EvalQuery(id="3", query="nothing", relevant=[RelevantItem(source="b.md")]),
    ]
    svc = FakeService()
    rep = run_eval(svc, queries, RunConfig("hybrid"), k=5, default_collection="default")  # type: ignore[arg-type]
    assert rep.n == 3
    assert rep.recall_at_k == pytest.approx(2 / 3)
    assert rep.mrr_at_k == pytest.approx((1 + 0.5 + 0) / 3)
    assert rep.hit_at_k == pytest.approx(2 / 3)
    assert rep.page_hit_at_k == 1.0
    assert svc.calls[0].query == "a"  # warm-up
    assert svc.calls[2].collections == ["other"]
    md = report_markdown([rep])
    assert "| hybrid |" in md and "Recall@5" in md
    assert report_markdown([]) == ""
    assert rep.summary()["queries"] == 3


def test_relevant_pages_list_accepts_any_page() -> None:
    q = EvalQuery(id="1", query="x", relevant=[RelevantItem(source="k.pdf", pages=[27, 28])])
    first, recall, _, page_hit = score_query(q, [hit(1, "k.pdf", 3), hit(2, "k.pdf", 28)], k=5)
    assert first == 2
    assert recall == 1.0
    assert page_hit is True
