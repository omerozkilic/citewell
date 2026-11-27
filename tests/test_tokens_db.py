"""Scoped API tokens end to end: store, REST, MCP over HTTP and the CLI."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from citewell import auth, config
from citewell.api import create_app
from citewell.app import Citewell
from citewell.store import NotFoundError

from .conftest import make_settings

pytestmark = pytest.mark.db

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def tokens(citewell: Citewell) -> Iterator[dict[str, str]]:
    """Three tokens: read of `default`, read/write of `default`, and read of everything."""
    made: dict[str, str] = {}
    for name, cols, write in [
        ("reader", ["default"], False),
        ("writer", ["default"], True),
        ("everything", None, False),
    ]:
        secret = auth.new_token()
        citewell.store.create_token(name, auth.hash_token(secret), cols, write)
        made[name] = secret
    yield made
    for name in made:
        citewell.store.revoke_token(name)


@pytest.fixture
def client(citewell: Citewell) -> Iterator[TestClient]:
    app = create_app(Citewell(make_settings(allowed_hosts=["testserver"])))
    with TestClient(app) as c:
        yield c


def test_store_token_lifecycle(citewell: Citewell) -> None:
    store = citewell.store
    secret = auth.new_token()
    info = store.create_token("lifecycle", auth.hash_token(secret), ["default", "default"], True)
    try:
        assert info.collections == ["default"] and info.can_write
        scope = store.token_scope(auth.hash_token(secret))
        assert scope is not None and scope.collections == frozenset({"default"}) and scope.can_write
        assert scope.token_name == "lifecycle"
        assert store.token_scope(auth.hash_token("nope")) is None
        assert "lifecycle" in {t.name for t in store.list_tokens()}
        with pytest.raises(ValueError, match="already exists"):
            store.create_token("lifecycle", auth.hash_token(auth.new_token()), None, False)
        with pytest.raises(NotFoundError, match="nonexistent"):
            store.create_token("bad", auth.hash_token(auth.new_token()), ["nonexistent"], False)
        with pytest.raises(ValueError, match="needs a name"):
            store.create_token("  ", auth.hash_token(auth.new_token()), None, False)
    finally:
        assert store.revoke_token("lifecycle")
    assert not store.revoke_token("lifecycle")
    assert store.token_scope(auth.hash_token(secret)) is None
    assert "lifecycle" not in {t.name for t in store.list_tokens()}
    revoked = [t for t in store.list_tokens(include_revoked=True) if t.name == "lifecycle"]
    assert revoked and revoked[0].revoked_at is not None
    # a revoked name can be reused
    again = store.create_token("lifecycle", auth.hash_token(auth.new_token()), None, False)
    assert again.collections is None
    store.revoke_token("lifecycle")


def test_has_active_tokens_handles_a_missing_table(citewell: Citewell) -> None:
    store = citewell.store
    assert not store.has_active_tokens()
    store.create_token("probe", auth.hash_token(auth.new_token()), None, False)
    assert store.has_active_tokens()
    store.revoke_token("probe")
    assert not store.has_active_tokens()
    with store.conn() as conn:
        conn.execute("ALTER TABLE api_tokens RENAME TO api_tokens_hidden")
        conn.commit()
    try:
        assert not store.has_active_tokens()  # a database from before this migration has no tokens
    finally:
        with store.conn() as conn:
            conn.execute("ALTER TABLE api_tokens_hidden RENAME TO api_tokens")
            conn.commit()


def test_server_is_open_until_a_token_exists(client: TestClient, tokens: dict[str, str]) -> None:
    assert client.get("/health").status_code == 200  # always exempt
    assert client.get("/v1/collections").status_code == 401
    assert client.get("/v1/collections", headers=_bearer("cw_wrong")).status_code == 401
    assert client.get("/v1/collections", headers={"Authorization": "Basic abc"}).status_code == 401
    assert client.get("/v1/collections", headers=_bearer(tokens["reader"])).status_code == 200


def test_rest_reads_are_limited_to_the_token_collections(client: TestClient, tokens: dict[str, str]) -> None:
    reader = _bearer(tokens["reader"])
    names = [c["name"] for c in client.get("/v1/collections", headers=reader).json()]
    assert names == ["default"]
    everything = _bearer(tokens["everything"])
    assert {"default", "handbook-en"} <= {
        c["name"] for c in client.get("/v1/collections", headers=everything).json()
    }

    ok = client.post("/v1/search", json={"query": "parola", "collections": ["default"]}, headers=reader)
    assert ok.status_code == 200 and ok.json()["hits"]
    denied = client.post(
        "/v1/search", json={"query": "password", "collections": ["handbook-en"]}, headers=reader
    )
    assert denied.status_code == 403 and "handbook-en" in denied.json()["detail"]
    star = client.post("/v1/search", json={"query": "password", "collections": ["*"]}, headers=reader)
    assert star.status_code == 200
    assert {h["collection"] for h in star.json()["hits"]} <= {"default"}
    assert (
        client.get("/v1/search", params={"q": "parola", "collection": "default"}, headers=reader).status_code
        == 200
    )
    assert (
        client.get("/v1/search", params={"q": "x", "collection": "handbook-en"}, headers=reader).status_code
        == 403
    )
    assert client.post("/v1/search", json={"query": "password"}, headers=reader).status_code == 200  # default

    en_hit = client.post(
        "/v1/search", json={"query": "password", "collections": ["handbook-en"]}, headers=everything
    )
    en_chunk = en_hit.json()["hits"][0]["chunk_id"]
    assert client.get(f"/v1/chunks/{en_chunk}", headers=reader).status_code == 403
    assert client.get(f"/v1/chunks/{en_chunk}", headers=everything).status_code == 200

    assert (
        client.get("/v1/documents", params={"collection": "handbook-en"}, headers=reader).status_code == 403
    )
    docs = client.get("/v1/documents", headers=reader).json()
    assert docs and {d["collection"] for d in docs} == {"default"}


def test_rest_verify_respects_scope(client: TestClient, tokens: dict[str, str]) -> None:
    everything = _bearer(tokens["everything"])
    reader = _bearer(tokens["reader"])
    hit = client.post(
        "/v1/search", json={"query": "password", "collections": ["handbook-en"]}, headers=everything
    )
    hit = hit.json()["hits"][0]
    body = {"quote": hit["quote"], "chunk_id": hit["chunk_id"]}
    assert client.post("/v1/verify", json=body, headers=reader).status_code == 403
    assert client.post("/v1/verify", json=body, headers=everything).status_code == 200
    unscoped = client.post("/v1/verify", json={"quote": hit["quote"]}, headers=reader)
    assert unscoped.status_code == 200 and not unscoped.json()["verified"]  # handbook-en is invisible to it
    named = client.post(
        "/v1/verify", json={"quote": hit["quote"], "collections": ["handbook-en"]}, headers=reader
    )
    assert named.status_code == 403


def test_rest_writes_need_a_writable_token(client: TestClient, tokens: dict[str, str]) -> None:
    reader, writer = _bearer(tokens["reader"]), _bearer(tokens["writer"])
    upload = {"files": {"file": ("scoped.txt", "Kapsamlı belge.".encode(), "text/plain")}}

    denied = [
        client.post("/v1/documents", **upload, headers=reader),
        client.post("/v1/collections", json={"name": "scoped-x"}, headers=reader),
        client.delete("/v1/documents", params={"collection": "default", "source": "x"}, headers=reader),
        client.delete("/v1/collections/default", headers=reader),
        client.post("/v1/documents", **upload, data={"collection": "handbook-en"}, headers=writer),
        client.post("/v1/collections", json={"name": "scoped-x"}, headers=writer),
        client.delete("/v1/collections/handbook-en", headers=writer),
        client.delete("/v1/documents", params={"collection": "handbook-en", "source": "x"}, headers=writer),
    ]
    assert [r.status_code for r in denied] == [403] * len(denied)

    done = client.post("/v1/documents", **upload, headers=writer)  # no collection: the default one
    assert done.status_code == 200, done.text
    removed = client.delete(
        "/v1/documents", params={"collection": "default", "source": "scoped.txt"}, headers=writer
    )
    assert removed.status_code == 204


def _mcp_call(client: TestClient, token: str, method: str, params: dict[str, Any]) -> dict[str, Any]:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    r = client.post("/mcp", json=body, headers={**MCP_HEADERS, **_bearer(token)})
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def test_mcp_over_http_is_scoped(client: TestClient, tokens: dict[str, str]) -> None:
    reader = tokens["reader"]
    assert client.post("/mcp", json={}, headers=MCP_HEADERS).status_code == 401

    listed = _mcp_call(client, reader, "tools/call", {"name": "list_collections", "arguments": {}})
    assert [c["name"] for c in listed["result"]["structuredContent"]["collections"]] == ["default"]

    ok = _mcp_call(
        client, reader, "tools/call", {"name": "search_documents", "arguments": {"query": "parola"}}
    )
    assert ok["result"]["structuredContent"]["passages"]

    denied = _mcp_call(
        client,
        reader,
        "tools/call",
        {"name": "search_documents", "arguments": {"query": "x", "collection": "handbook-en"}},
    )
    assert denied["result"]["isError"] and "handbook-en" in str(denied["result"]["content"])

    star = _mcp_call(
        client,
        reader,
        "tools/call",
        {"name": "search_documents", "arguments": {"query": "x", "collection": "*"}},
    )
    assert {p["collection"] for p in star["result"]["structuredContent"]["passages"]} <= {"default"}

    docs = _mcp_call(client, reader, "tools/call", {"name": "list_documents", "arguments": {}})
    assert {d["collection"] for d in docs["result"]["structuredContent"]["documents"]} == {"default"}
    bad_docs = _mcp_call(
        client, reader, "tools/call", {"name": "list_documents", "arguments": {"collection": "handbook-en"}}
    )
    assert bad_docs["result"]["isError"]

    everything = tokens["everything"]
    en = _mcp_call(
        client,
        everything,
        "tools/call",
        {"name": "search_documents", "arguments": {"query": "password", "collection": "handbook-en"}},
    )
    passage = en["result"]["structuredContent"]["passages"][0]
    chunk_args = {"name": "get_chunk", "arguments": {"chunk_id": passage["chunk_id"]}}
    assert _mcp_call(client, reader, "tools/call", chunk_args)["result"]["isError"]
    assert not _mcp_call(client, everything, "tools/call", chunk_args)["result"].get("isError")
    verify_args = {
        "name": "verify_quote",
        "arguments": {"quote": passage["quote"], "chunk_id": passage["chunk_id"]},
    }
    assert _mcp_call(client, reader, "tools/call", verify_args)["result"]["isError"]
    assert not _mcp_call(client, everything, "tools/call", verify_args)["result"].get("isError")
    verify_scoped = {"name": "verify_quote", "arguments": {"quote": passage["quote"]}}
    assert not _mcp_call(client, reader, "tools/call", verify_scoped)["result"]["structuredContent"][
        "verified"
    ]


def test_mcp_resources_and_completion_are_scoped(client: TestClient, tokens: dict[str, str]) -> None:
    reader, everything = tokens["reader"], tokens["everything"]
    res = _mcp_call(client, reader, "resources/read", {"uri": "citewell://collections"})
    assert '"handbook-en"' not in res["result"]["contents"][0]["text"]
    assert "error" in _mcp_call(
        client, reader, "resources/read", {"uri": "citewell://collections/handbook-en/documents"}
    )
    assert "result" in _mcp_call(
        client, reader, "resources/read", {"uri": "citewell://collections/default/documents"}
    )

    hit = _mcp_call(
        client,
        everything,
        "tools/call",
        {"name": "search_documents", "arguments": {"query": "password", "collection": "handbook-en"}},
    )["result"]["structuredContent"]["passages"][0]
    uri = f"citewell://chunks/{hit['chunk_id']}"
    assert "error" in _mcp_call(client, reader, "resources/read", {"uri": uri})
    assert "result" in _mcp_call(client, everything, "resources/read", {"uri": uri})

    comp = {
        "ref": {"type": "ref/prompt", "name": "answer_with_citations"},
        "argument": {"name": "collection", "value": ""},
    }
    assert _mcp_call(client, reader, "completion/complete", comp)["result"]["completion"]["values"] == [
        "default"
    ]


def test_env_token_stays_unrestricted_next_to_scoped_tokens(
    citewell: Citewell, tokens: dict[str, str]
) -> None:
    app = create_app(Citewell(make_settings(api_token="admin-secret")), mount_mcp=False)
    with TestClient(app) as c:
        assert c.get("/v1/collections").status_code == 401
        names = {x["name"] for x in c.get("/v1/collections", headers=_bearer("admin-secret")).json()}
        assert {"default", "handbook-en"} <= names
        assert [x["name"] for x in c.get("/v1/collections", headers=_bearer(tokens["reader"])).json()] == [
            "default"
        ]
        assert c.get("/v1/collections", headers=_bearer(tokens["everything"])).status_code == 200


def test_cli_tokens_roundtrip(citewell: Citewell, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from typer.testing import CliRunner

    from citewell.cli import app

    s = citewell.settings
    for key, value in {
        "DATABASE_URL": s.database_url,
        "EMBEDDING_BACKEND": "hash",
        "EMBEDDING_DIM": str(s.embedding_dim),
        "RERANKER_BACKEND": "lexical",
    }.items():
        monkeypatch.setenv(f"CITEWELL_{key}", value)
    config.get_settings.cache_clear()
    runner = CliRunner()
    try:
        assert runner.invoke(app, ["tokens", "create", "cli-test"]).exit_code == 1  # needs a scope
        both = runner.invoke(app, ["tokens", "create", "cli-test", "-c", "default", "--all-collections"])
        assert both.exit_code == 1 and "either" in both.output

        made = runner.invoke(app, ["tokens", "create", "cli-test", "-c", "default", "--write"])
        assert made.exit_code == 0, made.output
        secret = next(line for line in made.output.splitlines() if line.startswith("cw_"))
        assert "read/write" in made.output and "cannot be shown again" in made.output
        scope = citewell.store.token_scope(auth.hash_token(secret))
        assert scope is not None and scope.can_write

        dup = runner.invoke(app, ["tokens", "create", "cli-test", "--all-collections"])
        assert dup.exit_code == 1 and "already exists" in dup.output
        unknown = runner.invoke(app, ["tokens", "create", "cli-other", "-c", "missing-collection"])
        assert unknown.exit_code == 1 and "missing-collection" in unknown.output

        listed = runner.invoke(app, ["tokens", "list"])
        assert "cli-test" in listed.output and secret not in listed.output
        as_json = json.loads(runner.invoke(app, ["tokens", "list", "--json"]).output)
        assert [t["name"] for t in as_json if t["name"] == "cli-test"] == ["cli-test"]

        assert runner.invoke(app, ["tokens", "revoke", "cli-test"]).exit_code == 0
        assert runner.invoke(app, ["tokens", "revoke", "cli-test"]).exit_code == 1
        assert "cli-test" not in runner.invoke(app, ["tokens", "list"]).output
        assert "cli-test" in runner.invoke(app, ["tokens", "list", "--revoked"]).output

        everyone = runner.invoke(app, ["tokens", "create", "cli-all", "--all-collections"])
        assert (
            everyone.exit_code == 0
            and "all collections" in everyone.output
            and "read-only" in everyone.output
        )
        runner.invoke(app, ["tokens", "revoke", "cli-all"])
    finally:
        config.get_settings.cache_clear()


def test_rate_limit_is_per_token(citewell: Citewell, tokens: dict[str, str]) -> None:
    app = create_app(
        Citewell(make_settings(api_token="admin-secret", rate_limit_per_minute=2)), mount_mcp=False
    )
    with TestClient(app) as c:
        reader, everything = _bearer(tokens["reader"]), _bearer(tokens["everything"])
        assert [c.get("/v1/collections", headers=reader).status_code for _ in range(2)] == [200, 200]
        blocked = c.get("/v1/collections", headers=reader)
        assert blocked.status_code == 429
        assert blocked.json() == {"detail": "rate limit exceeded"}
        assert 1 <= int(blocked.headers["Retry-After"]) <= 60
        # other tokens and the admin token have their own budget; /health is not limited
        assert c.get("/v1/collections", headers=everything).status_code == 200
        admin = _bearer("admin-secret")
        assert [c.get("/v1/collections", headers=admin).status_code for _ in range(3)] == [200, 200, 429]
        assert all(c.get("/health").status_code == 200 for _ in range(5))
        # rejected credentials are not counted against anyone
        assert c.get("/v1/collections", headers=_bearer("cw_wrong")).status_code == 401


def test_rate_limit_keys_anonymous_clients_by_address(citewell: Citewell) -> None:
    app = create_app(Citewell(make_settings(rate_limit_per_minute=1)), mount_mcp=False)
    with TestClient(app) as c:
        assert c.get("/v1/collections").status_code == 200
        assert c.get("/v1/collections").status_code == 429
