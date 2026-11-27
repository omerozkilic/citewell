"""The /metrics endpoint: off by default, protected, and counting real traffic."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from citewell import auth
from citewell.api import create_app
from citewell.app import Citewell
from citewell.search import SearchRequest

from .conftest import make_settings

pytestmark = pytest.mark.db


def _value(text: str, series: str) -> float:
    match = re.search(rf"^{re.escape(series)} (\S+)$", text, re.MULTILINE)
    assert match, f"{series} not in:\n{text}"
    return float(match[1])


def test_metrics_are_off_by_default(citewell: Citewell) -> None:
    with TestClient(create_app(Citewell(make_settings()), mount_mcp=False)) as c:
        assert c.get("/metrics").status_code == 404
        assert c.get("/health").status_code == 200


def test_metrics_count_requests_searches_and_sizes(citewell: Citewell) -> None:
    app = create_app(Citewell(make_settings(metrics=True, allowed_hosts=["testserver"])))
    with TestClient(app) as c:
        c.get("/health")
        c.post("/v1/search", json={"query": "parola en az kaç karakter"})
        c.post("/v1/search", json={"query": "Dünyanın en yüksek dağı hangisidir?"})
        c.get("/v1/search", params={"q": "parola", "mode": "keyword"})
        assert c.post("/v1/search", json={"query": ""}).status_code == 422
        assert c.get("/v1/chunks/no-such-chunk").status_code == 404
        c.get("/no/such/path")
        c.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
        )
        r = c.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"] == "text/plain; version=0.0.4; charset=utf-8"
    text = r.text
    assert _value(text, 'citewell_http_requests_total{method="GET",route="/health",status="200"}') == 1
    assert _value(text, 'citewell_http_requests_total{method="POST",route="/v1/search",status="200"}') == 2
    assert (
        _value(text, 'citewell_http_requests_total{method="GET",route="/v1/chunks/{chunk_id}",status="404"}')
        == 1
    )
    assert 'route="/v1/chunks/no-such-chunk"' not in text  # route template, not the raw path
    assert _value(text, 'citewell_http_requests_total{method="GET",route="other",status="404"}') == 1
    assert _value(text, 'citewell_http_requests_total{method="POST",route="/mcp",status="200"}') == 1
    assert _value(text, 'citewell_searches_total{mode="hybrid",outcome="ok"}') == 1
    assert _value(text, 'citewell_searches_total{mode="hybrid",outcome="weak"}') == 1
    assert _value(text, 'citewell_searches_total{mode="keyword",outcome="ok"}') == 1
    assert _value(text, 'citewell_search_duration_seconds_count{mode="hybrid"}') == 2
    assert 'citewell_http_request_duration_seconds_bucket{route="/health",le="+Inf"} 1' in text
    assert _value(text, 'citewell_documents{collection="default"}') == 4
    assert _value(text, 'citewell_chunks{collection="handbook-en"}') >= 1
    assert re.search(r'^citewell_build_info\{version="[^"]+"\} 1$', text, re.MULTILINE)


def test_metrics_need_the_token_and_an_unrestricted_one(citewell: Citewell) -> None:
    scoped = auth.new_token()
    citewell.store.create_token("metrics-scoped", auth.hash_token(scoped), ["default"], False)
    try:
        settings = make_settings(metrics=True, api_token="admin-secret")
        with TestClient(create_app(Citewell(settings), mount_mcp=False)) as c:
            assert c.get("/metrics").status_code == 401
            assert c.get("/metrics", headers={"Authorization": "Bearer admin-secret"}).status_code == 200
            denied = c.get("/metrics", headers={"Authorization": f"Bearer {scoped}"})
            assert denied.status_code == 403 and "unrestricted" in denied.json()["detail"]
            text = c.get("/metrics", headers={"Authorization": "Bearer admin-secret"}).text
            assert _value(text, 'citewell_http_requests_total{method="GET",route="other",status="401"}') == 1
            assert (
                _value(text, 'citewell_http_requests_total{method="GET",route="/metrics",status="403"}') == 1
            )
    finally:
        citewell.store.revoke_token("metrics-scoped")


def test_search_errors_are_counted(citewell: Citewell) -> None:
    cw = Citewell(make_settings(metrics=True))
    try:
        with pytest.raises(ValueError, match="must not be empty"):
            cw.search.search(SearchRequest(query="  "))
        with pytest.raises(ValueError, match="mode must be one of"):
            cw.search.search(SearchRequest(query="x", mode="bogus"))
        text = cw.metrics.render()
        assert _value(text, 'citewell_searches_total{mode="hybrid",outcome="error"}') == 1
        assert _value(text, 'citewell_searches_total{mode="invalid",outcome="error"}') == 1
    finally:
        cw.close()


def test_searches_are_not_measured_when_metrics_are_off(citewell: Citewell) -> None:
    cw = Citewell(make_settings())
    try:
        cw.search.search(SearchRequest(query="parola"))
        assert cw.metrics.render() == "\n"
    finally:
        cw.close()
