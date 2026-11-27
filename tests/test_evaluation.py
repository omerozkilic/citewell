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

from .conftest import EVAL_TR, make_settings


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
    def __init__(self, confidence: float = 1.0) -> None:
        self.calls: list[SearchRequest] = []
        self.confidence = confidence
        self.settings = make_settings(answerable_threshold=0.5)

    def search(self, req: SearchRequest) -> SearchResponse:
        self.calls.append(req)
        hits = [hit(1, "a.pdf", 1), hit(2, "b.md")] if "a" in req.query else [hit(1, "z.md")]
        return SearchResponse(
            query=req.query,
            mode=req.mode,
            reranked=False,
            collections=[],
            took_ms=1,
            hits=hits,
            confidence=self.confidence,
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


def test_unanswerable_queries_are_judged_only_by_the_signal() -> None:
    queries = [
        EvalQuery(id="1", query="a", relevant=[RelevantItem(source="a.pdf", page=1)]),
        EvalQuery(id="2", query="a more", relevant=[RelevantItem(source="a.pdf", page=1)]),
        EvalQuery(id="3", query="not in the documents", answerable=False),
        EvalQuery(id="4", query="neither", answerable=False),
    ]
    # confidence 1.0 is above the 0.5 threshold: every question is flagged answerable
    rep = run_eval(FakeService(1.0), queries, RunConfig("hybrid"), k=5)  # type: ignore[arg-type]
    assert rep.n == 4
    assert rep.recall_at_k == 1.0  # unanswerable queries do not count towards ranking metrics
    assert rep.false_abstain_rate == 0.0 and rep.false_answer_rate == 1.0
    assert rep.summary()["false_answer_rate"] == 1.0 and rep.summary()["answerable_threshold"] == 0.5
    assert [q.expected_answerable for q in rep.queries] == [True, True, False, False]

    low = run_eval(FakeService(0.2), queries, RunConfig("hybrid"), k=5)  # type: ignore[arg-type]
    assert low.false_abstain_rate == 1.0 and low.false_answer_rate == 0.0

    # the threshold can be overridden per run
    tuned = run_eval(
        FakeService(0.2),
        queries,
        RunConfig("hybrid"),
        k=5,
        answerable_threshold=0.1,  # type: ignore[arg-type]
    )
    assert tuned.false_abstain_rate == 0.0 and tuned.answerable_threshold == 0.1


def test_only_unanswerable_queries_have_no_ranking_metrics() -> None:
    queries = [EvalQuery(id="1", query="nothing here", answerable=False)]
    rep = run_eval(FakeService(0.0), queries, RunConfig("hybrid"), k=5)  # type: ignore[arg-type]
    assert rep.recall_at_k == 0.0 and rep.mrr_at_k == 0.0 and rep.hit_at_k == 0.0
    assert rep.false_abstain_rate is None and rep.false_answer_rate == 0.0


def test_answerability_is_reported_for_every_dataset() -> None:
    plain = run_eval(
        FakeService(),  # type: ignore[arg-type]
        [EvalQuery(id="1", query="a", relevant=[RelevantItem(source="a.pdf")])],
        RunConfig("hybrid"),
    )
    # only answerable questions: the false-abstain rate exists, the false-answer rate does not
    assert plain.summary()["false_abstain_rate"] == 0.0 and "false_answer_rate" not in plain.summary()
    md = report_markdown([plain])
    assert md.splitlines()[0].endswith("False abstain | False answer |")
    assert md.splitlines()[2].endswith("| 0.000 | – |")

    mixed = run_eval(
        FakeService(),  # type: ignore[arg-type]
        [
            EvalQuery(id="1", query="a", relevant=[RelevantItem(source="a.pdf")]),
            EvalQuery(id="2", query="x", answerable=False),
        ],
        RunConfig("hybrid"),
    )
    assert report_markdown([mixed]).splitlines()[2].endswith("| 0.000 | 1.000 |")


def test_dataset_rejects_inconsistent_answerability(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least one relevant"):
        EvalQuery(id="x", query="q")
    with pytest.raises(ValueError, match="must not list relevant"):
        EvalQuery(id="x", query="q", answerable=False, relevant=[RelevantItem(source="a")])
