"""Metadata filters end to end: ingest (author, date, tags), search in all modes, REST, MCP, CLI."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from email.message import EmailMessage
from typing import Any

import pytest
from fastapi.testclient import TestClient

from citewell import config, db
from citewell.api import create_app
from citewell.app import Citewell
from citewell.models import SearchFilters
from citewell.search import SearchRequest

from .conftest import make_settings

pytestmark = pytest.mark.db

COL = "filters-test"
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _eml(sender: str, day: str, subject: str) -> bytes:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["Date"] = day
    msg.set_content("Yıllık izin talebi hakkında bilgi. İzin süresi yirmi gün.")
    return msg.as_bytes()


@pytest.fixture
def corpus(citewell: Citewell) -> Iterator[Citewell]:
    ing = citewell.ingest
    ing.ingest_bytes(
        _eml("Ayşe Yılmaz <ayse@example.com>", "Mon, 03 Nov 2025 09:00:00 +0300", "İzin onayı"),
        "ayse.eml",
        COL,
        "turkish",
        tags=["İK", "onay"],
    )
    ing.ingest_bytes(
        _eml("İlker Demir <ilker@example.com>", "Wed, 10 Jan 2024 09:00:00 +0300", "İzin talebi"),
        "ilker.eml",
        COL,
        tags=["ik"],
    )
    ing.ingest_bytes("Yıllık izin yönergesi. İzin hakkı her yıl yenilenir.".encode(), "yonerge.txt", COL)
    yield citewell
    citewell.store.delete_collection(COL)


def _sources(cw: Citewell, mode: str = "hybrid", **filters: Any) -> list[str]:
    resp = cw.search.search(
        SearchRequest(
            query="yıllık izin",
            top_k=10,
            mode=mode,
            collections=[COL],
            filters=SearchFilters(**filters),
        )
    )
    return sorted({h.source for h in resp.hits})


ALL = ["ayse.eml", "ilker.eml", "yonerge.txt"]


@pytest.mark.parametrize("mode", ["vector", "keyword", "hybrid"])
def test_every_filter_in_every_mode(corpus: Citewell, mode: str) -> None:
    assert _sources(corpus, mode) == ALL  # no filter: unchanged
    assert _sources(corpus, mode, file_types=["eml"]) == ["ayse.eml", "ilker.eml"]
    assert _sources(corpus, mode, file_types=["txt", "pdf"]) == ["yonerge.txt"]
    assert _sources(corpus, mode, author="ayşe") == ["ayse.eml"]
    assert _sources(corpus, mode, author="İLKER") == ["ilker.eml"]  # Turkish-aware case folding
    assert _sources(corpus, mode, date_from=date(2025, 1, 1)) == ["ayse.eml"]
    assert _sources(corpus, mode, date_to=date(2024, 12, 31)) == ["ilker.eml"]
    assert _sources(corpus, mode, date_from=date(2024, 1, 10), date_to=date(2025, 11, 3)) == [
        "ayse.eml",
        "ilker.eml",
    ]
    assert _sources(corpus, mode, tags=["ik"]) == ["ayse.eml", "ilker.eml"]
    assert _sources(corpus, mode, tags=["İK", "onay"]) == ["ayse.eml"]
    assert _sources(corpus, mode, file_types=["eml"], tags=["onay"], author="yılmaz") == ["ayse.eml"]
    assert _sources(corpus, mode, tags=["yok"]) == []
    assert _sources(corpus, mode, author="100%_") == []  # LIKE wildcards are escaped


def test_filters_keep_top_k_full(corpus: Citewell) -> None:
    resp = corpus.search.search(
        SearchRequest(query="izin", top_k=2, collections=[COL], filters=SearchFilters(file_types=["eml"]))
    )
    assert [h.source for h in resp.hits].count("yonerge.txt") == 0 and len(resp.hits) == 2


def test_documents_expose_metadata(corpus: Citewell) -> None:
    docs = {d.source: d for d in corpus.store.list_documents(COL)}
    assert docs["ayse.eml"].author == "Ayşe Yılmaz <ayse@example.com>"
    assert docs["ayse.eml"].doc_date == date(2025, 11, 3)
    assert docs["ayse.eml"].tags == ["ik", "onay"]
    assert docs["yonerge.txt"].author is None and docs["yonerge.txt"].doc_date is None
    assert docs["yonerge.txt"].tags == []


def test_reingest_with_force_replaces_tags(corpus: Citewell) -> None:
    corpus.ingest.ingest_bytes(
        _eml("Ayşe Yılmaz <ayse@example.com>", "Mon, 03 Nov 2025 09:00:00 +0300", "İzin onayı"),
        "ayse.eml",
        COL,
        force=True,
        tags=["arşiv"],
    )
    assert _sources(corpus, tags=["arşiv"]) == ["ayse.eml"]
    assert _sources(corpus, tags=["onay"]) == []


def test_migration_backfills_the_author_of_older_documents(corpus: Citewell) -> None:
    with corpus.store.conn() as conn:
        conn.execute("DELETE FROM citewell_migrations WHERE version = 5")
        conn.execute("DROP INDEX documents_tags_gin")
        conn.execute("ALTER TABLE documents DROP COLUMN author, DROP COLUMN doc_date, DROP COLUMN tags")
        conn.commit()
        assert db.pending_migrations(conn) == ["0005_document_metadata.sql"]
    corpus.check_schema()
    docs = {d.source: d for d in corpus.store.list_documents(COL)}
    assert docs["ilker.eml"].author == "İlker Demir <ilker@example.com>"
    assert docs["ilker.eml"].tags == [] and docs["ilker.eml"].doc_date is None


@pytest.fixture
def client(corpus: Citewell) -> Iterator[TestClient]:
    with TestClient(create_app(Citewell(make_settings(allowed_hosts=["testserver"])))) as c:
        yield c


def test_rest_filters(corpus: Citewell, client: TestClient) -> None:
    def post(**filters: Any) -> list[str]:
        body = {"query": "yıllık izin", "top_k": 10, "collections": [COL], "filters": filters}
        r = client.post("/v1/search", json=body)
        assert r.status_code == 200, r.text
        return sorted({h["source"] for h in r.json()["hits"]})

    assert post() == ALL
    assert post(file_types=["txt"]) == ["yonerge.txt"]
    assert post(author="ayşe", date_from="2025-01-01") == ["ayse.eml"]
    assert post(tags=["ik"]) == ["ayse.eml", "ilker.eml"]
    assert (
        client.post("/v1/search", json={"query": "x", "filters": {"file_types": ["a b"]}}).status_code == 422
    )

    params = {
        "q": "yıllık izin",
        "k": 10,
        "collection": COL,
        "type": "eml",
        "author": "ilker",
        "date_to": "2024-12-31",
    }
    got = client.get("/v1/search", params=params)
    assert [h["source"] for h in got.json()["hits"]] == ["ilker.eml"]
    both = client.get("/v1/search", params={"q": "izin", "collection": COL, "tag": ["ik", "onay"]})
    assert {h["source"] for h in both.json()["hits"]} == {"ayse.eml"}
    assert client.get("/v1/search", params={"q": "izin", "type": "a b"}).status_code == 400

    docs = client.get("/v1/documents", params={"collection": COL}).json()
    assert {d["source"]: d["tags"] for d in docs}["ayse.eml"] == ["ik", "onay"]


def test_rest_upload_with_tags(corpus: Citewell, client: TestClient) -> None:
    up = client.post(
        "/v1/documents",
        files={"file": ("notlar.txt", "Kahve makinesi üçüncü katta.".encode(), "text/plain")},
        data={"collection": COL, "tags": ["Mutfak", "ofis"]},
    )
    assert up.status_code == 200, up.text
    r = client.post(
        "/v1/search",
        json={"query": "kahve", "collections": [COL], "filters": {"tags": ["mutfak"]}},
    )
    assert [h["source"] for h in r.json()["hits"]] == ["notlar.txt"]


def test_mcp_search_filters(corpus: Citewell, client: TestClient) -> None:
    def call(**arguments: Any) -> list[str]:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search_documents",
                "arguments": {"query": "yıllık izin", "collection": COL, "top_k": 10, **arguments},
            },
        }
        r = client.post("/mcp", json=body, headers=HEADERS)
        assert r.status_code == 200, r.text
        result = r.json()["result"]
        assert not result.get("isError"), result
        return sorted({p["source"] for p in result["structuredContent"]["passages"]})

    assert call() == ALL
    assert call(file_type=["eml"], tags=["onay"]) == ["ayse.eml"]
    assert call(author="demir", date_to="2024-12-31") == ["ilker.eml"]
    assert call(date_from="2025-01-01") == ["ayse.eml"]


def test_cli_search_filters_and_ingest_tags(
    corpus: Citewell, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from typer.testing import CliRunner

    from citewell.cli import app

    s = corpus.settings
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
        base = ["search", "yıllık izin", "-c", COL, "--json", "-k", "10"]

        def sources(*extra: str) -> list[str]:
            res = runner.invoke(app, [*base, *extra])
            assert res.exit_code == 0, res.output
            return sorted({h["source"] for h in json.loads(res.output)["hits"]})

        assert sources() == ALL
        assert sources("-T", "eml", "--author", "ayşe", "--after", "2025-01-01") == ["ayse.eml"]
        assert sources("--before", "2024-12-31") == ["ilker.eml"]
        assert sources("-t", "onay") == ["ayse.eml"]
        bad = runner.invoke(app, [*base, "--after", "not-a-date"])
        assert bad.exit_code == 1 and "error" in bad.output

        note = tmp_path / "toplanti.txt"
        note.write_text("Toplantı notları: yıllık izin planı konuşuldu.", encoding="utf-8")
        done = runner.invoke(app, ["ingest", str(note), "-c", COL, "-t", "Toplantı", "--tag", "plan"])
        assert done.exit_code == 0, done.output
        assert sources("-t", "toplantı", "-t", "plan") == ["toplanti.txt"]
    finally:
        config.get_settings.cache_clear()
