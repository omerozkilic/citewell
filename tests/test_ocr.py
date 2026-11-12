"""OCR for scanned PDF pages (``CITEWELL_OCR=auto``)."""

from __future__ import annotations

import io
import logging
import shutil
import sys
import types
from pathlib import Path
from typing import Any, ClassVar

import pytest

from citewell import ocr
from citewell.doctor import check_ocr
from citewell.loaders import UnsupportedFormatError, load_bytes
from citewell.ocr import OcrOptions, OcrSession, OcrUnavailableError, check_available

from .conftest import make_settings

pytest.importorskip("reportlab")

FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def _pdf(text_pages: set[int], total: int) -> bytes:
    """A PDF where only ``text_pages`` (1-based) carry a text layer; the rest are blank like a scan."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    for n in range(1, total + 1):
        if n in text_pages:
            c.drawString(72, 750, f"Sayfa {n} gercek metin katmani tasir.")
        c.showPage()
    c.save()
    return buf.getvalue()


class FakeSession:
    instances: ClassVar[list[FakeSession]] = []
    fail: ClassVar[bool] = False

    def __init__(self, data: bytes, options: OcrOptions) -> None:
        self.options, self.calls, self.closed = options, [], False
        FakeSession.instances.append(self)

    def page_text(self, index: int) -> str:
        if FakeSession.fail:
            raise OcrUnavailableError("no tesseract")
        self.calls.append(index)
        return "" if index == 4 else f"Taranmis sayfa {index + 1} metni.\nIkinci satir."

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def fake_session(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeSession.instances, FakeSession.fail = [], False
    monkeypatch.setattr("citewell.loaders.OcrSession", FakeSession)


def test_without_ocr_scanned_pages_stay_empty_and_no_session_is_created() -> None:
    doc = load_bytes(_pdf({1}, 3), "t.pdf")
    assert [p.number for p in doc.pages] == [1]
    assert doc.metadata["pages_without_text"] == 2 and "ocr_pages" not in doc.metadata
    assert FakeSession.instances == []


def test_only_pages_without_a_text_layer_are_recognised() -> None:
    doc = load_bytes(_pdf({1}, 3), "t.pdf", ocr=OcrOptions())
    assert [(p.number, p.ocr) for p in doc.pages] == [(1, False), (2, True), (3, True)]
    assert doc.pages[1].text.startswith("Taranmis sayfa 2 metni.")
    assert doc.metadata["ocr_pages"] == [2, 3] and doc.metadata["pages_without_text"] == 0
    (session,) = FakeSession.instances
    assert session.calls == [1, 2] and session.closed  # the text page was never OCR'd


def test_text_pdfs_never_touch_the_ocr_engine() -> None:
    doc = load_bytes(_pdf({1, 2}, 2), "t.pdf", ocr=OcrOptions())
    assert [p.ocr for p in doc.pages] == [False, False]
    assert FakeSession.instances == []  # not even opened: no cost for text PDFs


def test_page_budget_limits_the_work_and_the_rest_is_reported_missing() -> None:
    doc = load_bytes(_pdf(set(), 3), "t.pdf", ocr=OcrOptions(max_pages=1))
    assert [p.number for p in doc.pages] == [1]
    assert doc.metadata["pages_without_text"] == 2
    assert FakeSession.instances[0].calls == [0]
    unlimited = load_bytes(_pdf(set(), 3), "t.pdf", ocr=OcrOptions(max_pages=0))
    assert len(unlimited.pages) == 3


def test_empty_recognition_result_is_not_recorded_as_ocr() -> None:
    doc = load_bytes(_pdf(set(), 5), "t.pdf", ocr=OcrOptions())  # page 5 recognises as empty
    assert [p.number for p in doc.pages] == [1, 2, 3, 4]
    assert doc.metadata["ocr_pages"] == [1, 2, 3, 4] and doc.metadata["pages_without_text"] == 1


def test_unavailable_ocr_is_reported_and_the_session_is_closed() -> None:
    FakeSession.fail = True
    with pytest.raises(UnsupportedFormatError, match="OCR is enabled but unavailable: no tesseract"):
        load_bytes(_pdf(set(), 2), "t.pdf", ocr=OcrOptions())
    assert FakeSession.instances[0].closed


# --------------------------------------------------------------------------- OcrSession


class _Image:
    def to_pil(self) -> str:
        return "image"


class _FakePage:
    closed = False
    scale = 0.0

    def render(self, scale: float) -> _Image:
        _FakePage.scale = scale
        return _Image()

    def close(self) -> None:
        _FakePage.closed = True


class _FakeTesseractError(RuntimeError):
    pass


class _FakeNotFound(OSError):
    pass


def _install_fakes(monkeypatch: pytest.MonkeyPatch, behaviour: Any = "metin") -> types.ModuleType:
    pdfium = types.ModuleType("pypdfium2")

    class Doc:
        def __init__(self, data: bytes) -> None:
            self.data = data

        def __getitem__(self, index: int) -> _FakePage:
            return _FakePage()

        def close(self) -> None:
            pass

    pdfium.PdfDocument = Doc  # type: ignore[attr-defined]
    tess = types.ModuleType("pytesseract")
    tess.TesseractError = _FakeTesseractError  # type: ignore[attr-defined]
    tess.TesseractNotFoundError = _FakeNotFound  # type: ignore[attr-defined]

    def image_to_string(image: Any, lang: str, timeout: int) -> str:
        if isinstance(behaviour, Exception):
            raise behaviour
        return f"{behaviour}|{lang}|{timeout}"

    tess.image_to_string = image_to_string  # type: ignore[attr-defined]
    tess.get_tesseract_version = lambda: "5.3.4"  # type: ignore[attr-defined]
    tess.get_languages = lambda: ["eng", "tur", "osd"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pypdfium2", pdfium)
    monkeypatch.setitem(sys.modules, "pytesseract", tess)
    return tess


def test_session_renders_at_the_requested_dpi_and_passes_language_and_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fakes(monkeypatch)
    session = OcrSession(b"%PDF", OcrOptions(languages="tur", dpi=144, timeout_s=7))
    assert session.page_text(0) == "metin|tur|7"
    assert _FakePage.scale == pytest.approx(2.0) and _FakePage.closed
    session.close()


def test_session_errors_map_to_clear_messages(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _install_fakes(monkeypatch, _FakeNotFound("nope"))
    with pytest.raises(OcrUnavailableError, match="tesseract-ocr-tur"):
        OcrSession(b"x", OcrOptions()).page_text(0)
    _install_fakes(monkeypatch, _FakeTesseractError("Failed loading language 'tur'"))
    with pytest.raises(OcrUnavailableError, match="Failed loading language"):
        OcrSession(b"x", OcrOptions()).page_text(0)
    _install_fakes(monkeypatch, RuntimeError("Tesseract process timeout"))
    with caplog.at_level(logging.WARNING):
        assert OcrSession(b"x", OcrOptions(timeout_s=3)).page_text(2) == ""
    assert "page 3 timed out after 3s" in caplog.text
    monkeypatch.setitem(sys.modules, "pytesseract", None)
    with pytest.raises(OcrUnavailableError, match=r"citewell\[ocr\]"):
        OcrSession(b"x", OcrOptions())


def test_check_available_reports_what_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    tess = _install_fakes(monkeypatch)
    assert check_available(OcrOptions("tur+eng")) == "tesseract 5.3.4, languages tur+eng"
    with pytest.raises(OcrUnavailableError, match="no language data for deu"):
        check_available(OcrOptions("tur+deu"))

    def not_found() -> str:
        raise _FakeNotFound("missing")

    tess.get_tesseract_version = not_found  # type: ignore[attr-defined]
    with pytest.raises(OcrUnavailableError, match="binary was not found"):
        check_available(OcrOptions())
    monkeypatch.setitem(sys.modules, "pypdfium2", None)
    with pytest.raises(OcrUnavailableError, match=r"citewell\[ocr\]"):
        check_available(OcrOptions())


def test_doctor_check_ocr(monkeypatch: pytest.MonkeyPatch) -> None:
    assert check_ocr(make_settings()) == []
    monkeypatch.setattr(ocr, "check_available", lambda options: "tesseract 5, languages tur+eng")
    ok = check_ocr(make_settings(ocr="auto"))[0]
    assert ok.status == "ok" and "tesseract 5" in ok.detail

    def broken(options: OcrOptions) -> str:
        raise OcrUnavailableError("the tesseract binary was not found")

    monkeypatch.setattr(ocr, "check_available", broken)
    bad = check_ocr(make_settings(ocr="auto"))[0]
    assert bad.status == "fail" and "CITEWELL_OCR=off" in bad.hint


# ------------------------------------------------------------------------ real tesseract


def _tesseract_with_turkish() -> bool:
    if not shutil.which("tesseract") or not FONT.exists():
        return False
    try:
        return "tur" in __import__("pytesseract").get_languages()
    except Exception:
        return False


@pytest.mark.skipif(not _tesseract_with_turkish(), reason="needs tesseract with Turkish data")
def test_a_scanned_turkish_page_becomes_searchable_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    monkeypatch.undo()  # use the real OcrSession, not the fake
    image = Image.new("L", (1240, 300), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(FONT), 44)
    draw.text((60, 60), "Yıllık izin başvurusu yönetici", font=font, fill=0)
    draw.text((60, 140), "onayı ile tamamlanır.", font=font, fill=0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawString(72, 750, "Birinci sayfa gercek metin.")
    c.showPage()
    c.drawImage(ImageReader(image), 0, 400, 595, 144)
    c.showPage()
    c.save()
    doc = load_bytes(buf.getvalue(), "tarama.pdf", ocr=OcrOptions(languages="tur+eng", dpi=300))
    assert [(p.number, p.ocr) for p in doc.pages] == [(1, False), (2, True)]
    text = " ".join(doc.pages[1].text.split()).lower()
    assert "yıllık izin başvurusu yönetici onayı ile tamamlanır" in text
