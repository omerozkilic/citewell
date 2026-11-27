"""Progress reporting for slow search stages (model loading, reranking), also over MCP."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from citewell.api import create_app
from citewell.app import Citewell
from citewell.mcp_server import build_server
from citewell.search import SearchRequest

from .conftest import make_settings

pytestmark = pytest.mark.db

Event = tuple[int, int, str]


def _fresh() -> Citewell:
    """A Citewell whose models are not loaded yet, like a server right after start-up."""
    return Citewell(make_settings())


def test_progress_names_the_slow_stages() -> None:
    cw = _fresh()
    try:
        events: list[Event] = []
        cw.search.search(SearchRequest(query="parola", rerank=True), lambda *e: events.append(e))
        assert [(i, n) for i, n, _ in events] == [(1, 4), (2, 4), (3, 4), (4, 4)]
        assert "embedding model" in events[0][2] and "reranker" in events[1][2]
        assert events[2][2] == "Searching…" and events[3][2].startswith("Reranking ")

        again: list[Event] = []  # everything is loaded now: only the retrieval and the rerank remain
        cw.search.search(SearchRequest(query="parola", rerank=True), lambda *e: again.append(e))
        assert [(i, n, m.split()[0]) for i, n, m in again] == [(1, 2, "Searching…"), (2, 2, "Reranking")]

        plain: list[Event] = []
        cw.search.search(SearchRequest(query="parola"), lambda *e: plain.append(e))
        assert plain == [(1, 1, "Searching…")]
    finally:
        cw.close()


def test_keyword_search_does_not_load_the_embedder() -> None:
    cw = _fresh()
    try:
        events: list[Event] = []
        cw.search.search(SearchRequest(query="parola", mode="keyword"), lambda *e: events.append(e))
        assert events == [(1, 1, "Searching…")]
        assert not cw.embedder_loaded
    finally:
        cw.close()


def test_a_failing_progress_callback_never_breaks_the_search() -> None:
    def boom(step: int, total: int, message: str) -> None:
        raise RuntimeError("client went away")

    cw = _fresh()
    try:
        assert cw.search.search(SearchRequest(query="parola"), boom).hits
    finally:
        cw.close()


def test_rerank_without_a_reranker_is_still_an_error() -> None:
    cw = Citewell(make_settings(reranker_backend="none"))
    try:
        events: list[Event] = []
        with pytest.raises(ValueError, match="no reranker"):
            cw.search.search(SearchRequest(query="parola", rerank=True), lambda *e: events.append(e))
        assert events[0][2].startswith("Loading the embedding model")  # then it stopped before searching
    finally:
        cw.close()


async def test_mcp_client_receives_progress_notifications() -> None:
    from mcp import Client

    cw = _fresh()
    try:
        received: list[tuple[float, float | None, str | None]] = []

        async def on_progress(progress: float, total: float | None, message: str | None) -> None:
            received.append((progress, total, message))

        async with Client(build_server(cw)) as mc:
            res = await mc.call_tool(
                "search_documents",
                {"query": "Parolalar en az kaç karakter olmalı?", "rerank": True},
                progress_callback=on_progress,
            )
            assert not res.is_error and res.structured_content is not None
            assert res.structured_content["passages"]
            plain = await mc.call_tool("search_documents", {"query": "parola"})  # no callback: still fine
            assert not plain.is_error
        assert [(p, t) for p, t, _ in received] == [(1, 4), (2, 4), (3, 4), (4, 4)]
        assert received[0][2] is not None and "embedding model" in received[0][2]
    finally:
        cw.close()


def test_http_transport_ignores_progress_tokens_gracefully() -> None:
    """The HTTP endpoint answers with plain JSON: a progress token must not break the call."""
    app = create_app(Citewell(make_settings(allowed_hosts=["testserver"])))
    with TestClient(app) as c:
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "search_documents",
                "arguments": {"query": "parola", "rerank": True},
                "_meta": {"progressToken": "p1"},
            },
        }
        r = c.post(
            "/mcp",
            json=body,
            headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["result"]["structuredContent"]["passages"]


def test_a_plain_search_service_has_no_models_to_load() -> None:
    from citewell.search import SearchService

    cw = _fresh()
    try:
        service = SearchService(
            cw.store, cw.embedder, cw.settings, cw.reranker
        )  # models handed in, as in tests
        events: list[Event] = []
        service.search(SearchRequest(query="parola", rerank=True), lambda *e: events.append(e))
        assert [(i, n) for i, n, _ in events] == [(1, 2), (2, 2)]
    finally:
        cw.close()
