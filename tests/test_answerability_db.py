"""The answerability signal through search, REST, MCP and the CLI."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from citewell import config
from citewell.api import create_app
from citewell.app import Citewell
from citewell.search import SearchRequest, SearchService

from .conftest import ROOT, make_settings

pytestmark = pytest.mark.db

ON_TOPIC = "Parolalar en az kaç karakter uzunluğunda olmalıdır?"
OFF_TOPIC = "Dünyanın en yüksek dağı hangisidir?"
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def test_search_reports_confidence_and_answerable(citewell: Citewell) -> None:
    good = citewell.search.search(SearchRequest(query=ON_TOPIC))
    assert good.answerable and good.confidence >= 0.5
    bad = citewell.search.search(SearchRequest(query=OFF_TOPIC))
    assert bad.hits and not bad.answerable and bad.confidence < citewell.settings.answerable_threshold


def test_threshold_is_configurable(citewell: Citewell) -> None:
    def search(threshold: float) -> bool:
        settings = make_settings(answerable_threshold=threshold)
        service = SearchService(citewell.store, citewell.embedder, settings, citewell.reranker)
        return service.search(SearchRequest(query=OFF_TOPIC)).answerable

    assert not search(0.35)
    assert search(0.0)  # 0 turns the signal off: results are always "answerable"
    with pytest.raises(ValueError, match="answerable_threshold"):
        make_settings(answerable_threshold=1.5)


def test_rerank_score_counts_towards_confidence(citewell: Citewell) -> None:
    resp = citewell.search.search(SearchRequest(query=ON_TOPIC, rerank=True))
    assert resp.reranked and resp.answerable


def test_no_collections_means_not_answerable(citewell: Citewell) -> None:
    resp = citewell.search.search(
        SearchRequest(query="parola", collections=["handbook-en"], source_prefix="nope")
    )
    assert not resp.hits and not resp.answerable and resp.confidence == 0.0


@pytest.fixture
def client(citewell: Citewell) -> Iterator[TestClient]:
    with TestClient(create_app(Citewell(make_settings(allowed_hosts=["testserver"])))) as c:
        yield c


def test_rest_and_mcp_expose_the_signal(client: TestClient) -> None:
    good = client.post("/v1/search", json={"query": ON_TOPIC}).json()
    bad = client.post("/v1/search", json={"query": OFF_TOPIC}).json()
    assert good["answerable"] is True and good["confidence"] > bad["confidence"]
    assert bad["answerable"] is False

    def call(query: str, **extra: Any) -> dict[str, Any]:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "search_documents", "arguments": {"query": query, **extra}},
        }
        r = client.post("/mcp", json=body, headers=HEADERS)
        assert r.status_code == 200, r.text
        out: dict[str, Any] = r.json()["result"]["structuredContent"]
        return out

    assert call(ON_TOPIC)["answerable"] is True and call(ON_TOPIC)["note"] is None
    weak = call(OFF_TOPIC)
    assert weak["answerable"] is False and "Weak match" in weak["note"] and weak["passages"]
    none = call(ON_TOPIC, source_prefix="no-such-file")
    assert "No matching passages" in none["note"] and not none["answerable"] and not none["passages"]


def test_cli_search_and_eval(citewell: Citewell, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from citewell.cli import app

    s = citewell.settings
    for key, value in {
        "DATABASE_URL": s.database_url,
        "EMBEDDING_BACKEND": "hash",
        "EMBEDDING_DIM": str(s.embedding_dim),
        "RERANKER_BACKEND": "lexical",
        "CHUNK_SIZE": str(s.chunk_size),
        "CHUNK_OVERLAP": str(s.chunk_overlap),
    }.items():
        monkeypatch.setenv(f"CITEWELL_{key}", value)
    config.get_settings.cache_clear()
    runner = CliRunner()
    try:
        assert "weak match" not in runner.invoke(app, ["search", ON_TOPIC]).output
        weak = runner.invoke(app, ["search", OFF_TOPIC])
        assert "weak match" in weak.output and "probably do not answer" in weak.output

        dataset = ROOT / "examples" / "eval" / "unanswerable.jsonl"
        report = tmp_path / "report.json"
        res = runner.invoke(app, ["eval", str(dataset), "-r", "hybrid", "-o", str(report), "--markdown"])
        assert res.exit_code == 0, res.output
        assert "False answer" in res.output
        run = json.loads(report.read_text(encoding="utf-8"))["runs"][0]
        assert run["false_answer_rate"] < 0.5 and "false_abstain_rate" not in run
        assert run["answerable_threshold"] == pytest.approx(0.35)
        queries = json.loads(report.read_text(encoding="utf-8"))["runs"][0]["per_query"]
        assert all(q["expected_answerable"] is False for q in queries)

        strict = runner.invoke(
            app, ["eval", str(dataset), "-r", "hybrid", "-o", str(report), "--answerable-threshold", "0.95"]
        )
        assert strict.exit_code == 0
        assert json.loads(report.read_text(encoding="utf-8"))["runs"][0]["false_answer_rate"] == 0.0
    finally:
        config.get_settings.cache_clear()
