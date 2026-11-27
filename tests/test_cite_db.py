"""Citation export through the store, REST and the CLI."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from citewell import auth, config
from citewell.api import create_app
from citewell.app import Citewell
from citewell.search import SearchRequest
from citewell.store import NotFoundError

from .conftest import make_settings

pytestmark = pytest.mark.db


@pytest.fixture
def chunks(citewell: Citewell) -> list[str]:
    resp = citewell.search.search(SearchRequest(query="parola en az kaç karakter", top_k=3))
    assert len(resp.hits) >= 2
    return [h.chunk_id for h in resp.hits]


def test_store_cite_items_keep_the_given_order(citewell: Citewell, chunks: list[str]) -> None:
    items = citewell.store.cite_items(list(reversed(chunks)))
    assert [i.chunk_id for i in items] == list(reversed(chunks))
    assert all(i.source and i.collection == "default" for i in items)
    assert citewell.store.cite_items([]) == []
    with pytest.raises(NotFoundError, match="nope"):
        citewell.store.cite_items([chunks[0], "nope"])


def test_store_cite_items_carry_document_metadata(citewell: Citewell) -> None:
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = "Toplantı notu"
    msg["From"] = "Ayşe Yılmaz <ayse@example.com>"
    msg["Date"] = "Mon, 03 Nov 2025 09:00:00 +0300"
    msg.set_content("Atıf dışa aktarma deneme metni.")
    citewell.ingest.ingest_bytes(msg.as_bytes(), "not.eml", "cite-test")
    try:
        hit = citewell.search.search(
            SearchRequest(query="atıf dışa aktarma", collections=["cite-test"])
        ).hits[0]
        (item,) = citewell.store.cite_items([hit.chunk_id])
        assert item.author == "Ayşe Yılmaz <ayse@example.com>" and item.doc_date.isoformat() == "2025-11-03"
        assert item.title == "Toplantı notu" and item.collection == "cite-test"
    finally:
        citewell.store.delete_collection("cite-test")


@pytest.fixture
def client(citewell: Citewell) -> Iterator[TestClient]:
    with TestClient(create_app(Citewell(make_settings()), mount_mcp=False)) as c:
        yield c


def test_rest_cite_formats(client: TestClient, chunks: list[str]) -> None:
    bib = client.post("/v1/cite", json={"chunk_ids": chunks[:2]})
    assert bib.status_code == 200 and bib.headers["content-type"].startswith("application/x-bibtex")
    assert bib.text.count("@misc{") == 2 and f"chunk {chunks[0]}" in bib.text

    csl = client.post("/v1/cite", json={"chunk_ids": chunks[:2], "format": "csl-json"})
    assert csl.headers["content-type"].startswith("application/json")
    assert [e["note"] for e in csl.json()] == [f"chunk {c}" for c in chunks[:2]]

    md = client.post("/v1/cite", json={"chunk_ids": chunks[:2], "format": "md"})
    assert md.headers["content-type"].startswith("text/markdown")
    assert md.text.startswith("[^1]: ") and "\n[^2]: " in md.text

    assert client.post("/v1/cite", json={"chunk_ids": ["nope"]}).status_code == 404
    assert client.post("/v1/cite", json={"chunk_ids": []}).status_code == 422
    assert client.post("/v1/cite", json={"chunk_ids": chunks, "format": "ris"}).status_code == 422


def test_rest_cite_respects_token_scope(citewell: Citewell, chunks: list[str]) -> None:
    en = citewell.search.search(SearchRequest(query="on-call handover", collections=["handbook-en"])).hits[0]
    secret = auth.new_token()
    citewell.store.create_token("cite-reader", auth.hash_token(secret), ["default"], False)
    try:
        with TestClient(create_app(Citewell(make_settings()), mount_mcp=False)) as c:
            headers = {"Authorization": f"Bearer {secret}"}
            assert c.post("/v1/cite", json={"chunk_ids": chunks[:1]}, headers=headers).status_code == 200
            denied = c.post("/v1/cite", json={"chunk_ids": [chunks[0], en.chunk_id]}, headers=headers)
            assert denied.status_code == 403 and "handbook-en" in denied.json()["detail"]
    finally:
        citewell.store.revoke_token("cite-reader")


def test_cli_cite(
    citewell: Citewell, chunks: list[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
        bib = runner.invoke(app, ["cite", chunks[0]])
        assert bib.exit_code == 0 and bib.output.startswith("@misc{") and chunks[0] in bib.output

        csl = runner.invoke(app, ["cite", *chunks[:2], "-f", "csl-json"])
        assert [e["note"] for e in json.loads(csl.output)] == [f"chunk {c}" for c in chunks[:2]]

        md = runner.invoke(app, ["cite", "-q", "parola en az kaç karakter", "-k", "2", "-f", "md", "--quote"])
        assert md.exit_code == 0, md.output
        assert md.output.count("[^") >= 2 and '"' in md.output  # quotes come from the search hits
        plain = runner.invoke(app, ["cite", "-q", "parola en az kaç karakter", "-k", "2", "-f", "md"])
        assert '"' not in plain.output

        target = tmp_path / "refs.bib"
        done = runner.invoke(app, ["cite", chunks[0], "-o", str(target)])
        assert done.exit_code == 0 and "written to" in done.output
        assert target.read_text(encoding="utf-8").startswith("@misc{")

        assert runner.invoke(app, ["cite"]).exit_code == 1
        assert runner.invoke(app, ["cite", chunks[0], "-q", "x"]).exit_code == 1
        missing = runner.invoke(app, ["cite", "no-such-chunk"])
        assert missing.exit_code == 1 and "chunk not found" in missing.output
        citewell.store.ensure_collection("cite-empty")
        none = runner.invoke(app, ["cite", "-q", "parola", "-c", "cite-empty"])
        assert none.exit_code == 1 and "no results to cite" in none.output
    finally:
        citewell.store.delete_collection("cite-empty")
        config.get_settings.cache_clear()
