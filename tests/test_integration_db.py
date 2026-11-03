"""Integration tests against a real PostgreSQL + pgvector (marked ``db``)."""

from __future__ import annotations

from typing import Any

import pytest

from citewell import db
from citewell.app import Citewell
from citewell.evaluation import RunConfig, load_dataset, run_eval
from citewell.search import SearchRequest
from citewell.store import NotFoundError, chunk_id

from .conftest import CORPUS, EVAL_TR, make_settings

pytestmark = pytest.mark.db


def test_collections_and_documents(citewell: Citewell) -> None:
    cols = {c.name: c for c in citewell.store.list_collections()}
    assert set(cols) == {"default", "handbook-en"}
    assert cols["default"].language == "turkish"
    assert cols["handbook-en"].language == "english"
    assert cols["default"].document_count == 4
    docs = {d.source: d for d in citewell.store.list_documents("default")}
    assert docs["calisan-el-kitabi.pdf"].page_count == 6
    assert docs["calisan-el-kitabi.pdf"].chunk_count >= 6


def test_reingest_is_idempotent(citewell: Citewell) -> None:
    results = citewell.ingest.ingest_paths([CORPUS])
    assert {r.status for r in results} == {"unchanged"}
    forced = citewell.ingest.ingest_paths([CORPUS / "uzaktan-calisma-yonergesi.md"], force=True)
    assert forced[0].status == "ingested"
    # Stable ids: same bytes -> same chunk ids.
    doc = next(
        d for d in citewell.store.list_documents("default") if d.source == "uzaktan-calisma-yonergesi.md"
    )
    expected = chunk_id("default", doc.source, doc.sha256, 0)
    assert citewell.store.get_chunk(expected).ord == 0


def test_hybrid_search_returns_page_citations(citewell: Citewell) -> None:
    resp = citewell.search.search(SearchRequest(query="Günlük yemek harcırahı ne kadar?", top_k=3))
    assert resp.mode == "hybrid" and resp.collections == ["default"]
    top = resp.hits[0]
    assert top.source == "calisan-el-kitabi.pdf" and top.page == 4
    assert "harcırah" in top.quote
    assert top.quote.replace("…", "") in top.text.replace("\n", " ") or top.quote.endswith("…")
    assert {"vector", "keyword", "rrf"} <= set(top.scores)


@pytest.mark.parametrize("mode", ["vector", "keyword"])
def test_single_retriever_modes(citewell: Citewell, mode: str) -> None:
    resp = citewell.search.search(SearchRequest(query="parola en az kaç karakter", mode=mode, top_k=2))
    assert resp.hits and resp.hits[0].source == "bilgi-guvenligi-politikasi.md"
    assert resp.hits[0].scores.get(mode) is not None


def test_turkish_stemming_matches_inflections(citewell: Citewell) -> None:
    # "parolalarımız" -> stem "parola"; must hit via keyword search alone
    resp = citewell.search.search(SearchRequest(query="parolalarımız", mode="keyword", top_k=1))
    assert resp.hits[0].source == "bilgi-guvenligi-politikasi.md"


def test_rerank_and_collections(citewell: Citewell) -> None:
    resp = citewell.search.search(
        SearchRequest(query="severity 1 acknowledge", collections=["handbook-en"], rerank=True, top_k=2)
    )
    assert resp.reranked
    assert resp.hits[0].source == "on-call-handbook.md"
    assert "rerank" in resp.hits[0].scores
    all_cols = citewell.search.search(SearchRequest(query="on-call rotation", collections=["*"], top_k=3))
    assert set(all_cols.collections) == {"default", "handbook-en"}
    with pytest.raises(NotFoundError):
        citewell.search.search(SearchRequest(query="x", collections=["yok"]))


def test_source_prefix_filter(citewell: Citewell) -> None:
    resp = citewell.search.search(
        SearchRequest(query="izin", source_prefix="uzaktan", top_k=5, mode="hybrid")
    )
    assert resp.hits and all(h.source.startswith("uzaktan") for h in resp.hits)


def test_search_validation(citewell: Citewell) -> None:
    with pytest.raises(ValueError):
        citewell.search.search(SearchRequest(query="  "))
    with pytest.raises(ValueError):
        citewell.search.search(SearchRequest(query="x", mode="magic"))


def test_neighbours(citewell: Citewell) -> None:
    hit = citewell.search.search(SearchRequest(query="yıllık izin devri", top_k=1)).hits[0]
    rows = citewell.store.neighbours(hit.chunk_id, window=1)
    assert hit.chunk_id in [r.chunk_id for r in rows]
    assert [r.ord for r in rows] == sorted(r.ord for r in rows)
    with pytest.raises(NotFoundError):
        citewell.store.neighbours("nope")


def test_eval_on_sample_corpus(citewell: Citewell) -> None:
    rep = run_eval(citewell.search, load_dataset(EVAL_TR), RunConfig("hybrid"), k=5)
    # Hash embeddings are lexical only; this is a regression floor, not a benchmark.
    assert rep.recall_at_k >= 0.8
    assert rep.page_hit_at_k is not None and rep.page_hit_at_k >= 0.8


def test_schema_mismatch_detected(citewell: Citewell) -> None:
    other = Citewell(make_settings(embedding_dim=128))
    try:
        with pytest.raises(db.SchemaMismatchError):
            other.check_schema()
    finally:
        other.close()


def test_collection_lifecycle(citewell: Citewell) -> None:
    with pytest.raises(ValueError):
        citewell.store.ensure_collection("Geçersiz Ad")
    res = citewell.ingest.ingest_bytes(b"# Not\nGecici bir not.", "not.md", collection="tmp-col")
    assert res.status == "ingested"
    assert citewell.ingest.ingest_bytes(b"x", "a.xlsx", collection="tmp-col").status == "error"
    assert citewell.ingest.ingest_bytes(b"   ", "bos.txt", collection="tmp-col").status == "skipped"
    assert citewell.store.delete_document("tmp-col", "not.md")
    assert not citewell.store.delete_document("tmp-col", "not.md")
    assert citewell.store.delete_collection("tmp-col")
    assert not citewell.store.delete_collection("tmp-col")


# --------------------------------------------------------------------- REST API


@pytest.fixture(scope="module")
def client(citewell: Citewell) -> Any:
    from fastapi.testclient import TestClient

    from citewell.api import create_app

    # Separate Citewell instance (own pool) so the app lifespan can close it.
    app = create_app(Citewell(make_settings(allowed_hosts=["testserver"])))
    with TestClient(app) as c:
        yield c


def test_api_health_and_search(client: Any) -> None:
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["database"] == "ok"
    r = client.post("/v1/search", json={"query": "Haftada kaç gün evden çalışabilirim?", "top_k": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["hits"][0]["source"] == "uzaktan-calisma-yonergesi.md"
    g = client.get("/v1/search", params={"q": "parola", "k": 1, "mode": "keyword"})
    assert g.json()["hits"][0]["source"] == "bilgi-guvenligi-politikasi.md"
    cid = body["hits"][0]["chunk_id"]
    assert client.get(f"/v1/chunks/{cid}", params={"context": 1}).status_code == 200
    assert client.get("/v1/chunks/nope").status_code == 404
    assert client.post("/v1/search", json={"query": "x", "collections": ["yok"]}).status_code == 404


def test_api_collections_documents_upload(client: Any) -> None:
    assert client.post("/v1/collections", json={"name": "api-test", "language": "simple"}).status_code == 201
    up = client.post(
        "/v1/documents",
        files={"file": ("notlar.txt", "Kahve makinesi üçüncü katta.".encode(), "text/plain")},
        data={"collection": "api-test"},
    )
    assert up.status_code == 200, up.text
    assert up.json()["status"] == "ingested"
    bad = client.post("/v1/documents", files={"file": ("a.exe", b"MZ", "application/octet-stream")})
    assert bad.status_code == 415
    docs = client.get("/v1/documents", params={"collection": "api-test"}).json()
    assert [d["source"] for d in docs] == ["notlar.txt"]
    assert (
        client.delete("/v1/documents", params={"collection": "api-test", "source": "notlar.txt"}).status_code
        == 204
    )
    assert client.delete("/v1/collections/api-test").status_code == 204
    assert client.delete("/v1/collections/api-test").status_code == 404
    assert any(c["name"] == "default" for c in client.get("/v1/collections").json())


def test_api_bearer_token(citewell: Citewell) -> None:
    from fastapi.testclient import TestClient

    from citewell.api import create_app

    s = make_settings(api_token="s3cret")
    with TestClient(create_app(Citewell(s), mount_mcp=False)) as c:
        assert c.get("/health").status_code == 200  # exempt
        assert c.get("/v1/collections").status_code == 401
        assert c.get("/v1/collections", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/v1/collections", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_mcp_over_http(client: Any) -> None:
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "t", "version": "0"},
        },
    }
    r = client.post("/mcp", json=init, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["result"]["serverInfo"]["name"] == "citewell"
    # DNS-rebinding protection rejects unknown Host headers.
    evil = client.post("/mcp", json=init, headers={**headers, "Host": "evil.example"})
    assert evil.status_code == 421


# -------------------------------------------------------------------- MCP server


async def test_mcp_tools_resources_prompts(citewell: Citewell) -> None:
    from mcp import Client

    from citewell.mcp_server import build_server

    server = build_server(citewell)
    async with Client(server) as mc:
        tools = {t.name: t for t in (await mc.list_tools()).tools}
        assert set(tools) == {"search_documents", "get_chunk", "list_collections", "list_documents"}
        assert tools["search_documents"].annotations is not None
        assert tools["search_documents"].annotations.read_only_hint is True

        res = await mc.call_tool("search_documents", {"query": "Evlilik izni kaç gün?", "top_k": 2})
        assert not res.is_error
        data = res.structured_content
        assert data is not None
        first = data["passages"][0]
        assert first["ref"] == "[1]"
        assert first["citation"] == "calisan-el-kitabi.pdf, s. 3"

        ch = await mc.call_tool("get_chunk", {"chunk_id": first["chunk_id"], "context": 1})
        assert ch.structured_content is not None
        assert ch.structured_content["chunk"]["chunk_id"] == first["chunk_id"]

        cols = await mc.call_tool("list_collections", {})
        assert cols.structured_content is not None
        assert {c["name"] for c in cols.structured_content["collections"]} >= {"default", "handbook-en"}
        docs = await mc.call_tool("list_documents", {"collection": "handbook-en"})
        assert docs.structured_content is not None
        assert docs.structured_content["documents"][0]["source"] == "on-call-handbook.md"

        missing = await mc.call_tool("get_chunk", {"chunk_id": "nope"})
        assert missing.is_error

        resource = await mc.read_resource(f"citewell://chunks/{first['chunk_id']}")
        text = resource.contents[0].text  # type: ignore[union-attr]
        assert text.startswith("[calisan-el-kitabi.pdf, s. 3")
        prompts = (await mc.list_prompts()).prompts
        assert [p.name for p in prompts] == ["answer_with_citations"]
        prompt = await mc.get_prompt("answer_with_citations", {"question": "İzin kaç gün?"})
        assert "İzin kaç gün?" in prompt.messages[0].content.text  # type: ignore[union-attr]


# --------------------------------------------------------------------------- CLI


def test_cli_search_and_lists(citewell: Citewell, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from typer.testing import CliRunner

    from citewell import config
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
        r = runner.invoke(app, ["search", "SMS ikinci faktör", "--json", "-k", "1"])
        assert r.exit_code == 0, r.output
        payload = json.loads(r.stdout)
        assert payload["hits"][0]["source"] == "bilgi-guvenligi-politikasi.md"
        r = runner.invoke(app, ["search", "SMS ikinci faktör", "--rerank"])
        assert r.exit_code == 0 and "bilgi-guvenligi-politikasi.md" in r.stdout
        assert runner.invoke(app, ["collections", "list", "--json"]).exit_code == 0
        assert runner.invoke(app, ["documents", "list"]).exit_code == 0
        assert runner.invoke(app, ["init"]).exit_code == 0
        assert runner.invoke(app, ["doctor"]).exit_code == 0
        r = runner.invoke(app, ["eval", str(EVAL_TR), "-r", "hybrid", "--fail-under", "0.5"])
        assert r.exit_code == 0, r.output
        assert runner.invoke(app, ["--version"]).exit_code == 0
    finally:
        config.get_settings.cache_clear()


def test_cli_ingest_collections_documents(
    citewell: Citewell, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from typer.testing import CliRunner

    from citewell import config
    from citewell.cli import app

    s = citewell.settings
    monkeypatch.setenv("CITEWELL_DATABASE_URL", s.database_url)
    monkeypatch.setenv("CITEWELL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("CITEWELL_EMBEDDING_DIM", str(s.embedding_dim))
    monkeypatch.setenv("CITEWELL_RERANKER_BACKEND", "none")
    config.get_settings.cache_clear()
    (tmp_path / "a.md").write_text("# Not\nToplantı odası rezervasyonu takvimden yapılır.", encoding="utf-8")
    (tmp_path / "bozuk.pdf").write_bytes(b"not a pdf")
    runner = CliRunner()
    try:
        assert (
            runner.invoke(
                app, ["collections", "create", "cli-test", "-l", "turkish", "-d", "deneme"]
            ).exit_code
            == 0
        )
        assert runner.invoke(app, ["collections", "create", "Bad Name"]).exit_code == 1
        r = runner.invoke(app, ["ingest", str(tmp_path), "-c", "cli-test"])
        assert r.exit_code == 2, r.output  # one file failed
        assert "ingested" in r.output and "error" in r.output
        r = runner.invoke(app, ["search", "toplantı odası", "-c", "cli-test", "--full"])
        assert r.exit_code == 0 and "a.md" in r.stdout
        r = runner.invoke(app, ["search", "zzzqqq", "-c", "cli-test", "-m", "keyword"])
        assert r.exit_code == 0
        out = tmp_path / "report.json"
        r = runner.invoke(app, ["eval", str(EVAL_TR), "-r", "keyword", "-o", str(out), "--markdown"])
        assert r.exit_code == 0 and out.exists()
        assert runner.invoke(app, ["eval", str(EVAL_TR), "-r", "bad+x"]).exit_code == 1
        assert (
            runner.invoke(app, ["eval", str(EVAL_TR), "-r", "keyword", "--fail-under", "1.01"]).exit_code == 3
        )
        assert runner.invoke(app, ["documents", "list", "-c", "cli-test", "--json"]).exit_code == 0
        assert runner.invoke(app, ["documents", "delete", "a.md", "-c", "cli-test"]).exit_code == 0
        assert runner.invoke(app, ["documents", "delete", "a.md", "-c", "cli-test"]).exit_code == 1
        assert runner.invoke(app, ["collections", "delete", "cli-test", "-y"]).exit_code == 0
        assert runner.invoke(app, ["collections", "delete", "cli-test", "-y"]).exit_code == 1
        assert runner.invoke(app, ["models", "download", "--no-reranker"]).exit_code == 0
    finally:
        config.get_settings.cache_clear()


def test_ingest_warns_about_pages_without_text(citewell: Citewell, tmp_path: Any) -> None:
    from reportlab.pdfgen import canvas

    pdf = tmp_path / "taranmis.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(72, 750, "Sadece bu sayfada metin var.")
    c.showPage()
    for _ in range(3):
        c.rect(72, 600, 200, 100, fill=1)
        c.showPage()
    c.save()
    res = citewell.ingest.ingest_paths([pdf], collection="scan-test")[0]
    assert res.status == "ingested"
    assert res.message is not None and res.message.startswith("3/4 pages have no extractable text")
    doc = citewell.store.list_documents("scan-test")[0]
    assert doc.page_count == 4
    assert doc.pages_without_text == 3
    citewell.store.delete_collection("scan-test")


def test_preload_is_noop_for_hash_backend(citewell: Citewell) -> None:
    assert citewell.preload() is None
    other = Citewell(make_settings(preload_models=False))
    assert other.preload() is None
