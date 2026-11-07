import pytest
from pydantic import ValidationError

from citewell.config import Settings
from citewell.models import Citation


def test_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CITEWELL_EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
    monkeypatch.setenv("CITEWELL_DEFAULT_TOP_K", "9")
    s = Settings()
    assert s.embedding_model == "intfloat/multilingual-e5-large"
    assert s.default_top_k == 9


def test_overlap_must_be_smaller_than_chunk() -> None:
    with pytest.raises(ValidationError):
        Settings(chunk_size=100, chunk_overlap=100)


def test_citation_label() -> None:
    assert Citation(source="a.pdf", page=3, chunk_id="x", quote="q").label() == "a.pdf, s. 3"
    assert Citation(source="b.md", section="Giriş", chunk_id="x", quote="q").label() == "b.md, Giriş"
    assert Citation(source="c.txt", chunk_id="x", quote="q").label() == "c.txt"


def test_unreachable_database_fails_fast() -> None:
    import time

    from citewell.db import DatabaseUnavailableError, create_pool, describe_url

    assert describe_url("postgresql://u:secret@db.example:6543/x") == "db.example:6543/x"
    assert "secret" not in describe_url("postgresql://u:secret@h/x")
    t0 = time.perf_counter()
    with pytest.raises(DatabaseUnavailableError, match="docker compose up -d db"):
        create_pool("postgresql://citewell:citewell@127.0.0.1:1/citewell")
    assert time.perf_counter() - t0 < 10


def test_cli_reports_unreachable_database(monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from citewell import config
    from citewell.cli import app

    monkeypatch.setenv("CITEWELL_DATABASE_URL", "postgresql://citewell:citewell@127.0.0.1:1/citewell")
    config.get_settings.cache_clear()
    try:
        r = CliRunner().invoke(app, ["init"])
    finally:
        config.get_settings.cache_clear()
    assert r.exit_code == 1
    assert "cannot connect to PostgreSQL at 127.0.0.1:1/citewell" in r.output


def test_citation_label_with_page_labels() -> None:
    from citewell.models import citation_label

    assert citation_label("k.pdf", 17, None, "12") == "k.pdf, s. 12 (PDF s. 17)"
    assert citation_label("k.pdf", 3, None, "3") == "k.pdf, s. 3"
    assert citation_label("k.pdf", 3, None, None) == "k.pdf, s. 3"
    assert (
        Citation(source="k.pdf", page=2, page_label="ii", chunk_id="x", quote="q").label()
        == "k.pdf, s. ii (PDF s. 2)"
    )
