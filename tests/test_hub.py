import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from citewell import hub


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    for var in (
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "HF_HUB_CACHE",
        "HUGGINGFACE_HUB_CACHE",
        "XDG_CACHE_HOME",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    monkeypatch.delitem(sys.modules, "huggingface_hub", raising=False)
    yield tmp_path / "hf" / "hub"
    os.environ.pop("HF_HUB_OFFLINE", None)  # prefer_offline() writes os.environ directly


def _cache(root: Path, name: str) -> None:
    snap = root / f"models--{name.replace('/', '--')}" / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")


def test_cache_dir_resolution(clean_env: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert hub.hub_cache_dir() == clean_env
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path / "x"))
    assert hub.hub_cache_dir() == tmp_path / "x"


def test_prefer_offline_only_when_everything_is_cached(
    clean_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    _cache(clean_env, "BAAI/bge-m3")
    assert hub.is_model_cached("BAAI/bge-m3")
    assert not hub.is_model_cached("BAAI/bge-reranker-v2-m3")
    assert hub.prefer_offline(["BAAI/bge-m3", "BAAI/bge-reranker-v2-m3"]) is False
    assert "HF_HUB_OFFLINE" not in os.environ

    _cache(clean_env, "BAAI/bge-reranker-v2-m3")
    assert hub.prefer_offline(["BAAI/bge-m3", "BAAI/bge-reranker-v2-m3"]) is True
    assert os.environ["HF_HUB_OFFLINE"] == "1"


def test_user_choice_wins(clean_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _cache(clean_env, "m/x")
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    assert hub.prefer_offline(["m/x"]) is False
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    assert hub.prefer_offline(["m/y"]) is True


def test_too_late_after_import(clean_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import types

    _cache(clean_env, "m/x")
    monkeypatch.setitem(sys.modules, "huggingface_hub", types.ModuleType("huggingface_hub"))
    assert hub.prefer_offline(["m/x"]) is False
    assert "HF_HUB_OFFLINE" not in os.environ


def test_local_directory_counts_as_cached(tmp_path: Path) -> None:
    assert hub.is_model_cached(str(tmp_path))


def test_offline_load_failure_is_actionable(monkeypatch: pytest.MonkeyPatch) -> None:
    from citewell.embeddings import load_cached_first

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")

    def factory(name: str, **kw: object) -> str:
        raise OSError("missing file")

    with pytest.raises(RuntimeError, match="citewell models download"):
        load_cached_first(factory, "m/x")
