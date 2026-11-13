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
        assert set(tools) == {
            "search_documents",
            "get_chunk",
            "list_collections",
            "list_documents",
            "verify_quote",
        }
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

        checked = await mc.call_tool(
            "verify_quote", {"quote": first["quote"][:120], "chunk_id": first["chunk_id"]}
        )
        assert checked.structured_content is not None
        assert checked.structured_content["verified"] is True
        assert tools["verify_quote"].annotations is not None
        assert tools["verify_quote"].annotations.read_only_hint is True

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


# ---------------------------------------------------------------------- verify


def test_verify_quote_service(citewell: Citewell) -> None:
    v = citewell.verifier
    hit = citewell.search.search(SearchRequest(query="Günlük yemek harcırahı", top_k=1)).hits[0]

    exact = v.verify("Günlük yemek harcırahı yurt içinde 750 TL'dir.", chunk_id=hit.chunk_id)
    assert exact.verified
    assert exact.match == "exact"
    assert exact.page == 4
    assert exact.citation == "calisan-el-kitabi.pdf, s. 4"

    by_source = v.verify("GÜNLÜK YEMEK HARCIRAHI yurt içinde 750 TL'dir", source="calisan-el-kitabi.pdf")
    assert by_source.verified
    assert by_source.match == "normalized"

    searched = v.verify(
        "Parolalar en az 14 karakter uzunluğunda olmalıdır."
    )  # no hint: searches all collections
    assert searched.verified
    assert searched.source == "bilgi-guvenligi-politikasi.md"
    assert searched.section == "Bilgi Güvenliği Politikası > Parola Kuralları"

    wrong = v.verify("Günlük yemek harcırahı yurt içinde 1.000 TL olarak ödenir.", chunk_id=hit.chunk_id)
    assert not wrong.verified
    assert wrong.match in ("fuzzy", "not_found")

    paraphrase = v.verify("Yemek harcırahı yurt içinde günlük 750 TL'dir.", chunk_id=hit.chunk_id)
    assert not paraphrase.verified
    assert paraphrase.match == "fuzzy"
    assert paraphrase.source_text is not None
    assert "750 TL" in paraphrase.source_text

    missing = v.verify("Şirket her çalışana yılda iki kez ikramiye öder.")
    assert not missing.verified
    assert missing.match == "not_found"

    with pytest.raises(ValueError, match="too short"):
        v.verify("kısa")
    with pytest.raises(NotFoundError):
        v.verify("bir şey bir şey", source="yok.pdf")


def test_verify_quote_rest_and_cli(client: Any, citewell: Citewell, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from citewell import config
    from citewell.cli import app

    r = client.post(
        "/v1/verify", json={"quote": "Deneme süresi işe başlangıç tarihinden itibaren iki aydır."}
    )
    assert r.status_code == 200, r.text
    assert r.json()["verified"] is True
    assert r.json()["page"] == 1

    s = citewell.settings
    monkeypatch.setenv("CITEWELL_DATABASE_URL", s.database_url)
    monkeypatch.setenv("CITEWELL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("CITEWELL_EMBEDDING_DIM", str(s.embedding_dim))
    monkeypatch.setenv("CITEWELL_RERANKER_BACKEND", "none")
    monkeypatch.setenv("CITEWELL_CHUNK_SIZE", str(s.chunk_size))
    monkeypatch.setenv("CITEWELL_CHUNK_OVERLAP", str(s.chunk_overlap))
    config.get_settings.cache_clear()
    try:
        runner = CliRunner()
        ok = runner.invoke(
            app, ["verify", "Ekran, 5 dakika işlem yapılmadığında otomatik olarak kilitlenir."]
        )
        assert ok.exit_code == 0, ok.output
        assert "verified" in ok.stdout
        bad = runner.invoke(
            app, ["verify", "Ekran 30 saniye sonra kendiliğinden kapanır ve kilitlenir.", "--json"]
        )
        assert bad.exit_code == 4
    finally:
        config.get_settings.cache_clear()


def test_page_labels_end_to_end(citewell: Citewell, tmp_path: Any) -> None:
    from citewell.mcp_server import _passage

    from .test_loaders import _labelled_pdf

    pdf = tmp_path / "kitap.pdf"
    _labelled_pdf(pdf)
    assert citewell.ingest.ingest_paths([pdf], collection="labels-test")[0].status == "ingested"
    hit = citewell.search.search(
        SearchRequest(query="Birinci bolum metni", collections=["labels-test"], top_k=1, mode="keyword")
    ).hits[0]
    assert (hit.page, hit.page_label) == (3, "1")
    assert _passage(hit).citation == "kitap.pdf, s. 1 (PDF s. 3)"
    check = citewell.verifier.verify("Birinci bolum metni.", chunk_id=hit.chunk_id)
    assert check.citation == "kitap.pdf, s. 1 (PDF s. 3)"
    citewell.store.delete_collection("labels-test")


def test_pending_migrations_are_applied_on_startup(citewell: Citewell) -> None:
    from citewell import db

    with citewell.store.conn() as conn:
        conn.execute("DELETE FROM citewell_migrations WHERE version = 2")
        conn.execute("ALTER TABLE chunks DROP COLUMN page_label")
        conn.commit()
        assert db.pending_migrations(conn) == ["0002_page_labels.sql"]
    citewell.check_schema()  # an upgraded install: applies 0002 instead of failing
    with citewell.store.conn() as conn:
        assert db.pending_migrations(conn) == []
    assert citewell.search.search(SearchRequest(query="parola", top_k=1)).hits


def test_search_without_turkish_characters(citewell: Citewell) -> None:
    q = "ucak biletleri hangi sinifta alinir"  # "uçak biletleri hangi sınıfta alınır"
    hits = citewell.search.search(SearchRequest(query=q, mode="keyword", top_k=1)).hits
    assert hits
    assert (hits[0].source, hits[0].page) == ("calisan-el-kitabi.pdf", 4)
    assert "Uçak biletleri" in hits[0].quote

    strict = Citewell(make_settings(fold_diacritics=False))
    try:
        strict_hits = strict.search.search(
            SearchRequest(query="sinifinda ucak", mode="keyword", top_k=1)
        ).hits
        assert not strict_hits or strict_hits[0].page != 4
    finally:
        strict.close()


def test_folded_index_backfilled_by_migration(citewell: Citewell) -> None:
    from citewell import db

    with citewell.store.conn() as conn:
        before = dict(conn.execute("SELECT id, tsv_folded::text FROM chunks").fetchall())
        conn.execute("UPDATE chunks SET tsv_folded = NULL")
        conn.execute("DELETE FROM citewell_migrations WHERE version = 3")
        conn.commit()
        assert "0003_folded_search.sql" in db.pending_migrations(conn)
    citewell.check_schema()
    with citewell.store.conn() as conn:
        after = dict(conn.execute("SELECT id, tsv_folded::text FROM chunks").fetchall())
    assert after == before  # SQL back-fill folds exactly like the Python indexer


async def test_mcp_collection_completion_and_documents_template(citewell: Citewell) -> None:
    import json

    from mcp import Client
    from mcp.types import PromptReference, ResourceTemplateReference

    from citewell.mcp_server import build_server

    async with Client(build_server(citewell)) as mc:
        res = await mc.complete(
            PromptReference(type="ref/prompt", name="answer_with_citations"),
            {"name": "collection", "value": "hand"},
        )
        assert res.completion.values == ["handbook-en"]
        everything = await mc.complete(
            ResourceTemplateReference(
                type="ref/resource", uri="citewell://collections/{collection}/documents"
            ),
            {"name": "collection", "value": ""},
        )
        assert {"default", "handbook-en"} <= set(everything.completion.values)
        other = await mc.complete(
            PromptReference(type="ref/prompt", name="answer_with_citations"),
            {"name": "question", "value": "x"},
        )
        assert other.completion.values == []

        templates = (await mc.list_resource_templates()).resource_templates
        assert "citewell://collections/{collection}/documents" in {t.uri_template for t in templates}
        docs = await mc.read_resource("citewell://collections/handbook-en/documents")
        payload = json.loads(docs.contents[0].text)  # type: ignore[union-attr]
        assert [d["source"] for d in payload["documents"]] == ["on-call-handbook.md"]


def test_cli_ingest_prune(citewell: Citewell, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from typer.testing import CliRunner

    from citewell import config
    from citewell.cli import app

    s = citewell.settings
    monkeypatch.setenv("CITEWELL_DATABASE_URL", s.database_url)
    monkeypatch.setenv("CITEWELL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("CITEWELL_EMBEDDING_DIM", str(s.embedding_dim))
    monkeypatch.setenv("CITEWELL_RERANKER_BACKEND", "none")
    config.get_settings.cache_clear()
    folder = tmp_path / "docs"
    folder.mkdir()
    for name in ("a.md", "b.md", "c.md"):
        (folder / name).write_text(f"# {name}\nToplantı notu {name} için içerik.", encoding="utf-8")
    runner = CliRunner()
    try:
        assert runner.invoke(app, ["ingest", str(folder), "-c", "prune-test"]).exit_code == 0
        (folder / "b.md").unlink()
        (folder / "c.md").unlink()

        declined = runner.invoke(app, ["ingest", str(folder), "-c", "prune-test", "--prune"], input="n\n")
        assert declined.exit_code == 0, declined.output
        assert "b.md" in declined.output
        assert "not pruned" in declined.output
        assert len(citewell.store.list_documents("prune-test")) == 3

        confirmed = runner.invoke(app, ["ingest", str(folder), "-c", "prune-test", "--prune"], input="y\n")
        assert confirmed.exit_code == 0, confirmed.output
        assert [d.source for d in citewell.store.list_documents("prune-test")] == ["a.md"]
        assert "2 removed" in confirmed.output

        empty = tmp_path / "empty"
        empty.mkdir()
        guarded = runner.invoke(app, ["ingest", str(empty), "-c", "prune-test", "--prune", "--yes"])
        assert guarded.exit_code == 0
        assert "not pruning" in guarded.output
        assert len(citewell.store.list_documents("prune-test")) == 1
    finally:
        config.get_settings.cache_clear()
        citewell.store.delete_collection("prune-test")


def test_search_statement_timeout(citewell: Citewell) -> None:
    from citewell.store import QueryTimeoutError

    store = citewell.store
    original = store.statement_timeout_ms
    store.statement_timeout_ms = 50
    try:
        with pytest.raises(QueryTimeoutError), store.read_tx() as conn:
            conn.execute("SELECT pg_sleep(2)")
        # The pooled connection is usable afterwards.
        with store.read_tx() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)
    finally:
        store.statement_timeout_ms = original


def test_api_rejects_oversized_query(citewell: Citewell) -> None:
    from fastapi.testclient import TestClient

    from citewell.api import create_app
    from citewell.config import MAX_QUERY_CHARS

    with TestClient(create_app(citewell, mount_mcp=False)) as c:
        too_long = "a" * (MAX_QUERY_CHARS + 1)
        assert c.get("/v1/search", params={"q": too_long}).status_code == 422
        assert c.post("/v1/search", json={"query": too_long}).status_code == 422


def test_doctor_on_a_healthy_database(citewell: Citewell) -> None:
    from citewell.doctor import check_database, has_failures

    checks = {c.name: c for c in check_database(make_settings())}
    assert not has_failures(list(checks.values()))
    assert checks["pgvector"].status in ("ok", "warn")
    assert checks["embedding dimension"].status == "ok"
    assert checks["migrations"].status == "ok"


def test_doctor_detects_dimension_mismatch_without_changing_anything(citewell: Citewell) -> None:
    from citewell.doctor import check_database

    checks = {c.name: c for c in check_database(make_settings(embedding_dim=128))}
    assert checks["embedding dimension"].status == "fail"
    assert "re-ingest" in checks["embedding dimension"].hint
    assert {c.name: c for c in check_database(make_settings())}["embedding dimension"].status == "ok"


def test_doctor_reports_pending_migrations_read_only(citewell: Citewell) -> None:
    import psycopg

    from citewell.doctor import check_database

    with psycopg.connect(make_settings().database_url, autocommit=True) as conn:
        row = conn.execute(
            "SELECT version, name FROM citewell_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        conn.execute("DELETE FROM citewell_migrations WHERE version = %s", (row[0],))
        try:
            checks = {c.name: c for c in check_database(make_settings())}
            assert checks["migrations"].status == "warn"
            assert row[1] in checks["migrations"].detail
            # doctor is read-only: it must not have applied the migration itself
            count = conn.execute(
                "SELECT count(*) FROM citewell_migrations WHERE version = %s", (row[0],)
            ).fetchone()
            assert count == (0,)
        finally:
            conn.execute("INSERT INTO citewell_migrations (version, name) VALUES (%s, %s)", (row[0], row[1]))


def test_doctor_on_an_uninitialised_database(citewell: Citewell) -> None:
    import psycopg

    from citewell.doctor import check_database

    with psycopg.connect(make_settings().database_url, autocommit=True) as conn:
        conn.execute("ALTER TABLE citewell_meta RENAME TO citewell_meta_bak")
        try:
            checks = {c.name: c for c in check_database(make_settings())}
            assert checks["schema"].status == "fail" and "citewell init" in checks["schema"].hint
        finally:
            conn.execute("ALTER TABLE citewell_meta_bak RENAME TO citewell_meta")


def test_cli_eval_baseline_roundtrip(
    citewell: Citewell, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json as _json

    from typer.testing import CliRunner

    from citewell import config
    from citewell.cli import app

    monkeypatch.setenv("CITEWELL_DATABASE_URL", make_settings().database_url)
    monkeypatch.setenv("CITEWELL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("CITEWELL_EMBEDDING_DIM", "256")
    monkeypatch.setenv("CITEWELL_RERANKER_BACKEND", "lexical")
    config.get_settings.cache_clear()
    runner = CliRunner()
    path = tmp_path / "baseline.json"
    try:
        args = ["eval", str(EVAL_TR), "-r", "hybrid"]
        assert runner.invoke(app, [*args, "--write-baseline", str(path)]).exit_code == 0
        assert runner.invoke(app, [*args, "--baseline", str(path)]).exit_code == 0

        data = _json.loads(path.read_text())
        data["runs"]["hybrid"]["recall@k"] = 1.0
        data["runs"]["hybrid"]["mrr@k"] = 1.0
        path.write_text(_json.dumps(data))
        result = runner.invoke(app, [*args, "--baseline", str(path), "--tolerance", "0"])
        assert result.exit_code == 3, result.output
        assert "regressed" in result.output

        data["k"] = 99
        path.write_text(_json.dumps(data))
        assert runner.invoke(app, [*args, "--baseline", str(path)]).exit_code == 1
    finally:
        config.get_settings.cache_clear()


def test_watch_keeps_a_collection_in_sync(citewell: Citewell, tmp_path: Any) -> None:
    import os

    from citewell.watch import Watcher

    # Own instance: an earlier CLI test closes the shared fixture's connection pool.
    cw = Citewell(make_settings())
    try:
        note = tmp_path / "not.md"
        note.write_text("# Not\n\nYıllık izin başvurusu yönetici onayı ile tamamlanır.", encoding="utf-8")
        watcher = Watcher(cw.ingest, cw.store, [tmp_path], "watch-test", "turkish", prune=True)
        first = watcher.poll(initial=True)
        assert [e.kind for e in first] == ["ingested"], first
        assert [d.source for d in cw.store.list_documents("watch-test")] == ["not.md"]
        hits = cw.search.search(SearchRequest(query="yıllık izin başvurusu", collections=["watch-test"])).hits
        assert hits and hits[0].source == "not.md"

        note.write_text("# Not\n\nSeyahat masrafları fatura ile iade edilir.", encoding="utf-8")
        os.utime(note, ns=(2 * 10**18, 2 * 10**18))
        watcher.poll()
        assert [e.kind for e in watcher.poll()] == ["ingested"]

        note.unlink()
        watcher.poll()
        assert [e.kind for e in watcher.poll()] == ["removed"]
        assert cw.store.list_documents("watch-test") == []
    finally:
        cw.close()


def _watch_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, fake_run: Any) -> Any:
    from typer.testing import CliRunner

    from citewell import config
    from citewell.cli import app

    monkeypatch.setattr("citewell.watch.run_watch", fake_run)
    monkeypatch.setenv("CITEWELL_DATABASE_URL", make_settings().database_url)
    monkeypatch.setenv("CITEWELL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("CITEWELL_EMBEDDING_DIM", "256")
    config.get_settings.cache_clear()
    try:
        return CliRunner().invoke(app, ["watch", str(tmp_path), "-c", "watch-test"])
    finally:
        config.get_settings.cache_clear()


def test_cli_watch_prints_events(citewell: Citewell, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from citewell.watch import WatchEvent

    def fake_run(watcher: Any, interval: float, on_event: Any) -> None:
        on_event(WatchEvent("ingested", "a.md", "2 chunks"))
        on_event(WatchEvent("unchanged", "b.md"))
        on_event(WatchEvent("error", "c.md", "ValueError: bad"))
        on_event(WatchEvent("removed", "d.md"))

    result = _watch_cli(monkeypatch, tmp_path, fake_run)
    assert result.exit_code == 0, result.output
    assert "ingested a.md — 2 chunks" in result.output
    assert "error c.md — ValueError: bad" in result.output
    assert "removed d.md" in result.output
    assert "b.md" not in result.output  # unchanged files are not news


def test_cli_watch_reports_failures(
    citewell: Citewell, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(*_: Any, **__: Any) -> None:
        raise RuntimeError("index unavailable")

    result = _watch_cli(monkeypatch, tmp_path, fake_run)
    assert result.exit_code == 1
    assert "index unavailable" in result.output


def test_cli_watch_stops_cleanly(citewell: Citewell, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(*_: Any, **__: Any) -> None:
        raise KeyboardInterrupt

    result = _watch_cli(monkeypatch, tmp_path, interrupted)
    assert result.exit_code == 0, result.output
    assert "watching" in result.output and "stopped" in result.output


def test_table_values_are_retrievable_with_pdf_tables(citewell: Citewell, tmp_path: Any) -> None:
    pytest.importorskip("pdfplumber")
    from .test_pdf_tables import FEES, PROSE, _pdf

    pdf = tmp_path / "tarife.pdf"
    pdf.write_bytes(_pdf([PROSE], ["Tarife", FEES, "Yilda bir guncellenir."]))
    cw = Citewell(make_settings(pdf_tables=True))
    try:
        results = cw.ingest.ingest_paths([pdf], collection="tables-test")
        assert [r.status for r in results] == ["ingested"]
        hits = cw.search.search(
            SearchRequest(query="basvuru ucreti 1500", collections=["tables-test"], mode="keyword")
        ).hits
        assert hits and hits[0].page == 2
        assert "| Basvuru ucreti | 1500 | 5 gun |" in hits[0].text
    finally:
        cw.close()


def test_scanned_pages_are_searchable_with_ocr_and_listed(
    citewell: Citewell, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from .test_ocr import FakeSession, _pdf

    FakeSession.instances, FakeSession.fail = [], False
    monkeypatch.setattr("citewell.loaders.OcrSession", FakeSession)
    pdf = tmp_path / "tarama.pdf"
    pdf.write_bytes(_pdf({1}, 3))
    plain = Citewell(make_settings())
    scanning = Citewell(make_settings(ocr="auto"))
    try:
        # Off by default: only the page with a text layer is indexed, and the user is told how to fix it.
        first = plain.ingest.ingest_paths([pdf], collection="ocr-test")[0]
        assert first.status == "ingested" and "CITEWELL_OCR=auto" in (first.message or "")
        assert plain.store.list_documents("ocr-test")[0].ocr_pages is None

        second = scanning.ingest.ingest_paths([pdf], collection="ocr-test", force=True)[0]
        assert second.status == "ingested" and second.message is None
        (doc,) = scanning.store.list_documents("ocr-test")
        assert doc.ocr_pages == [2, 3] and doc.pages_without_text == 0
        hits = scanning.search.search(
            SearchRequest(query="Taranmis sayfa 3 metni", collections=["ocr-test"], mode="keyword")
        ).hits
        assert hits and hits[0].page == 3
    finally:
        plain.close()
        scanning.close()


def test_documents_list_shows_ocr_pages(citewell: Citewell, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from citewell import config
    from citewell.cli import app

    monkeypatch.setenv("CITEWELL_DATABASE_URL", make_settings().database_url)
    monkeypatch.setenv("CITEWELL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("CITEWELL_EMBEDDING_DIM", "256")
    config.get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["documents", "list", "-c", "ocr-test"])
    finally:
        config.get_settings.cache_clear()
    assert result.exit_code == 0 and "3 (2 OCR)" in result.stdout, result.stdout


def test_cli_ingest_prints_warnings_for_pages_without_text(
    citewell: Citewell, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from reportlab.pdfgen import canvas
    from typer.testing import CliRunner

    from citewell import config
    from citewell.cli import app

    pdf = tmp_path / "karisik.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(72, 750, "Birinci sayfada gercek metin var.")
    c.showPage()
    c.showPage()  # a blank page, like a scan without OCR
    c.save()
    monkeypatch.setenv("CITEWELL_DATABASE_URL", make_settings().database_url)
    monkeypatch.setenv("CITEWELL_EMBEDDING_BACKEND", "hash")
    monkeypatch.setenv("CITEWELL_EMBEDDING_DIM", "256")
    monkeypatch.delenv("CITEWELL_OCR", raising=False)
    config.get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["ingest", str(pdf), "-c", "warn-test", "--force"])
    finally:
        config.get_settings.cache_clear()
    assert result.exit_code == 0, result.output
    assert "karisik.pdf" in result.output
    assert "⚠ 1/2 pages have no extractable text" in result.output
    assert "CITEWELL_OCR=auto" in result.output
