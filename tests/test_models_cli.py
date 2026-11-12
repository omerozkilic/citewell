"""``citewell models download`` prints the revision to pin."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

from citewell import config
from citewell.cli import app


class _Model:
    def __init__(self, name: str, dim: int = 4) -> None:
        self.name = name
        self.dim = dim


@pytest.fixture
def download(monkeypatch: pytest.MonkeyPatch) -> Any:
    calls: dict[str, Any] = {}

    def fake_embedder(backend: str, model: str, dim: int, **kw: Any) -> _Model:
        calls["embedding_revision"] = kw.get("revision")
        return _Model(model, dim)

    def fake_reranker(backend: str, model: str, **kw: Any) -> _Model:
        calls["reranker_revision"] = kw.get("revision")
        return _Model(model)

    monkeypatch.setattr("citewell.embeddings.build_embedder", fake_embedder)
    monkeypatch.setattr("citewell.rerank.build_reranker", fake_reranker)
    monkeypatch.setattr("citewell.hub.cached_revision", lambda model: f"hash-of-{model.split('/')[-1]}")
    monkeypatch.setenv("CITEWELL_EMBEDDING_BACKEND", "sentence-transformers")
    monkeypatch.setenv("CITEWELL_RERANKER_BACKEND", "sentence-transformers")

    def run(*args: str) -> Any:
        config.get_settings.cache_clear()
        try:
            return CliRunner().invoke(app, ["models", "download", *args]), calls
        finally:
            config.get_settings.cache_clear()

    return run


def test_download_prints_the_revision_to_pin(download: Any) -> None:
    result, _ = download()
    assert result.exit_code == 0
    assert "CITEWELL_EMBEDDING_REVISION=hash-of-bge-m3" in result.output
    assert "CITEWELL_RERANKER_REVISION=hash-of-bge-reranker-v2-m3" in result.output


def test_download_uses_configured_revisions(download: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CITEWELL_EMBEDDING_REVISION", "pinned1")
    monkeypatch.setenv("CITEWELL_RERANKER_REVISION", "pinned2")
    result, calls = download()
    assert calls == {"embedding_revision": "pinned1", "reranker_revision": "pinned2"}
    assert "pinned to revision pinned1" in result.output
    assert "pinned to revision pinned2" in result.output


def test_download_without_reranker(download: Any) -> None:
    result, calls = download("--no-reranker")
    assert result.exit_code == 0
    assert "reranker_revision" not in calls


def test_download_hash_backend_has_nothing_to_do(download: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CITEWELL_EMBEDDING_BACKEND", "hash")
    result, _ = download("--no-reranker")
    assert "nothing to download" in result.output


def test_download_without_a_cached_revision_prints_no_pin(
    download: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("citewell.hub.cached_revision", lambda model: None)
    result, _ = download("--no-reranker")
    assert result.exit_code == 0
    assert "REVISION=" not in result.output
