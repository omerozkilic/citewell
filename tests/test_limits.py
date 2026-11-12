"""Parser safety limits and model pinning."""

from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

from citewell import hub
from citewell.loaders import LimitExceededError, LoadLimits, UnsupportedFormatError, load_bytes


def _zip_bytes(payload: int) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"0" * payload)
    return buf.getvalue()


def test_docx_zip_bomb_is_rejected() -> None:
    bomb = _zip_bytes(60 * 1024 * 1024)  # compresses to a few tens of KB
    with pytest.raises(LimitExceededError):
        load_bytes(bomb, "bomb.docx", limits=LoadLimits(max_unpacked_bytes=0, max_zip_ratio=200))
    with pytest.raises(LimitExceededError):
        load_bytes(bomb, "bomb.docx", limits=LoadLimits(max_unpacked_bytes=50 * 1024 * 1024))


def test_invalid_docx_is_reported() -> None:
    with pytest.raises(UnsupportedFormatError):
        load_bytes(b"not a zip", "x.docx")


def test_pdf_page_limit() -> None:
    from pypdf import PdfWriter

    w = PdfWriter()
    for _ in range(3):
        w.add_blank_page(72, 72)
    buf = io.BytesIO()
    w.write(buf)
    with pytest.raises(LimitExceededError):
        load_bytes(buf.getvalue(), "big.pdf", limits=LoadLimits(max_pages=2))
    load_bytes(buf.getvalue(), "big.pdf", limits=LoadLimits(max_pages=0))  # 0 disables the limit


def test_cached_revision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    repo = tmp_path / "models--acme--m"
    (repo / "refs").mkdir(parents=True)
    (repo / "refs" / "main").write_text("abc123\n")
    assert hub.cached_revision("acme/m") == "abc123"
    assert hub.cached_revision("acme/missing") is None


def test_trust_remote_code_is_never_enabled() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "citewell"
    offenders = [p.name for p in root.glob("*.py") if "trust_remote_code" in p.read_text()]
    assert offenders == []


def test_cached_revision_falls_back_to_a_single_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HF_HUB_CACHE", str(tmp_path))
    snaps = tmp_path / "models--acme--m" / "snapshots"
    (snaps / "aaa111").mkdir(parents=True)
    assert hub.cached_revision("acme/m") == "aaa111"
    (snaps / "bbb222").mkdir()
    assert hub.cached_revision("acme/m") is None  # ambiguous: do not guess


def test_docx_without_python_docx_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "docx", None)  # makes ``import docx`` fail
    with pytest.raises(UnsupportedFormatError, match="citewell\\[docx\\]"):
        load_bytes(_zip_bytes(10), "ok.docx")
