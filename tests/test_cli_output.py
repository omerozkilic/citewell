"""CLI messages that contain square brackets (``citewell[models]``) must be printed verbatim."""

from __future__ import annotations

import sys

import pytest
from rich.console import Console
from typer.testing import CliRunner

from citewell import cli, config
from citewell.cli import app

UNREACHABLE = "postgresql://citewell:citewell@127.0.0.1:1/citewell"


@pytest.fixture
def recorded(monkeypatch: pytest.MonkeyPatch) -> Console:
    console = Console(record=True, width=200, force_terminal=False)
    monkeypatch.setattr(cli, "console", console)
    return console


def test_fail_keeps_the_extra_name_in_install_hints(recorded: Console) -> None:
    cli._fail("The sentence-transformers backend needs the 'models' extra: pip install 'citewell[models]'")
    assert "pip install 'citewell[models]'" in recorded.export_text()


def test_fail_does_not_interpret_markup_in_messages(recorded: Console) -> None:
    cli._fail("bad value [bold]x[/bold] in [red]config[/red]")
    assert "[bold]x[/bold] in [red]config[/red]" in recorded.export_text()


def test_doctor_hints_keep_the_extras(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CITEWELL_DATABASE_URL", UNREACHABLE)
    monkeypatch.setenv("CITEWELL_EMBEDDING_BACKEND", "sentence-transformers")
    monkeypatch.setenv("CITEWELL_PDF_TABLES", "true")
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)  # as if the extra is not installed
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    config.get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["doctor"])
    finally:
        config.get_settings.cache_clear()
    assert result.exit_code == 1
    assert "citewell[models]" in result.output
    assert "citewell[tables]" in result.output
