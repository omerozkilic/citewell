"""``citewell doctor`` checks that do not need a database."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest
from typer.testing import CliRunner

from citewell import config
from citewell.cli import app
from citewell.doctor import Check, check_database, check_models, check_server, has_failures, run_checks

from .conftest import make_settings

UNREACHABLE = "postgresql://citewell:citewell@127.0.0.1:1/citewell"


def _by_name(checks: list[Check]) -> dict[str, Check]:
    return {c.name: c for c in checks}


def test_unreachable_database_fails_with_a_hint() -> None:
    checks = check_database(make_settings(database_url=UNREACHABLE))
    assert [c.name for c in checks] == ["database"]
    assert checks[0].status == "fail"
    assert "127.0.0.1:1/citewell" in checks[0].detail
    assert "docker compose up -d db" in checks[0].hint
    assert "citewell:citewell" not in checks[0].detail  # no credentials in the output
    assert has_failures(checks)


@pytest.fixture
def fake_st(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.ModuleType("sentence_transformers"))


def _st_settings() -> config.Settings:
    return make_settings(
        embedding_backend="sentence-transformers",
        embedding_model="acme/embed",
        reranker_backend="sentence-transformers",
        reranker_model="acme/rerank",
    )


def test_models_not_cached_warn_and_fail_when_offline_is_required(
    fake_st: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    checks = _by_name(check_models(_st_settings()))
    assert checks["embeddings"].status == "warn"
    assert checks["offline"].status == "warn"
    assert "models download" in checks["offline"].hint

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    assert _by_name(check_models(_st_settings()))["offline"].status == "fail"


def test_cached_models_are_offline_ready(
    fake_st: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    for repo in ("models--acme--embed", "models--acme--rerank"):
        snap = tmp_path / repo / "snapshots" / "abc123"
        snap.mkdir(parents=True)
        (snap / "config.json").write_text("{}")
    checks = _by_name(check_models(_st_settings()))
    assert checks["embeddings"].status == "ok"
    assert checks["reranker"].status == "ok"
    assert checks["offline"].status == "ok"


def test_missing_sentence_transformers_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # ``import`` raises ImportError
    checks = _by_name(
        check_models(make_settings(embedding_backend="sentence-transformers", reranker_backend="none"))
    )
    assert checks["embeddings"].status == "fail"
    assert "citewell[models]" in checks["embeddings"].hint


def test_hash_backend_is_flagged_as_testing_only() -> None:
    checks = _by_name(check_models(make_settings()))
    assert checks["embeddings"].status == "warn"
    assert checks["reranker"].status == "ok"
    assert "offline" not in checks  # nothing to download


def test_api_token_check() -> None:
    assert check_server(make_settings(host="127.0.0.1"))[0].status == "ok"
    exposed = check_server(make_settings(host="0.0.0.0"))[0]
    assert exposed.status == "warn" and "CITEWELL_API_TOKEN" in exposed.hint
    assert check_server(make_settings(host="0.0.0.0", api_token="x"))[0].status == "ok"


def test_run_checks_lists_versions_first() -> None:
    names = [c.name for c in run_checks(make_settings(database_url=UNREACHABLE))]
    assert names[:2] == ["citewell", "python"]
    assert "database" in names and "api token" in names


def test_cli_json_output_and_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CITEWELL_DATABASE_URL", UNREACHABLE)
    monkeypatch.setenv("CITEWELL_EMBEDDING_BACKEND", "hash")
    config.get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["doctor", "--json"])
        human = CliRunner().invoke(app, ["doctor"])
    finally:
        config.get_settings.cache_clear()
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert any(c["name"] == "database" and c["status"] == "fail" for c in payload["checks"])
    assert human.exit_code == 1
    assert "cannot connect" in human.output
