"""The sample-file generator (scripts/make_sample_files.py) produces files Citewell can load."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType

import pytest

from citewell.loaders import LimitExceededError, LoadLimits, iter_files, load_file
from citewell.ocr import OcrOptions

from .conftest import ROOT

pytest.importorskip("reportlab")
pytest.importorskip("PIL")


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "make_sample_files", ROOT / "scripts" / "make_sample_files.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def samples(tmp_path_factory: pytest.TempPathFactory) -> Path:
    mod = _script()
    out = tmp_path_factory.mktemp("samples")
    if mod.find_font() is None:
        pytest.skip("needs a TrueType font with Turkish letters")
    assert mod.main([str(out)]) == 0
    return out


def test_every_format_loads_with_the_expected_content(samples: Path) -> None:
    docs = {p.name: load_file(p) for p, _ in iter_files([samples / "formats"])}
    assert set(docs) == {
        "sunum.pptx",
        "butce.xlsx",
        "personel.csv",
        "eski-kayit.csv",
        "kitap.epub",
        "iade.eml",
    }
    assert [(p.number, p.section) for p in docs["sunum.pptx"].pages] == [
        (1, "Yıllık Hedefler"),
        (2, "Bütçe Dağılımı"),
        (3, "Takvim"),
    ]
    assert [p.section for p in docs["butce.xlsx"].pages] == [
        "Personel",
        "Bütçe 2026",
    ]  # the hidden sheet is skipped
    assert "Zeynep Kaya | Hukuk | Bursa" in docs["personel.csv"].pages[0].text
    assert "Çanta | 5" in docs["eski-kayit.csv"].pages[0].text  # cp1254 decoded
    assert [p.section for p in docs["kitap.epub"].pages] == ["Giriş", "Güvenlik"]
    eml = docs["iade.eml"].pages[0].text
    assert "Seyahat masrafları fatura ile iade edilir." in eml and "GIZLI-EK-ICERIK" not in eml


def test_table_pdf_becomes_markdown_only_when_asked(samples: Path) -> None:
    pytest.importorskip("pdfplumber")
    path = samples / "pdf" / "tarife-tablolu.pdf"
    assert "|" not in load_file(path).pages[0].text
    from citewell.loaders import load_bytes

    text = load_bytes(path.read_bytes(), path.name, pdf_tables=True).pages[0].text
    assert "| Başvuru ücreti | 1500 | 5 gün |" in text or "| Basvuru ucreti | 1500 | 5 gun |" in text


def test_scanned_pdf_has_no_text_on_pages_two_and_three(samples: Path) -> None:
    doc = load_file(samples / "pdf" / "taranmis.pdf")
    assert [p.number for p in doc.pages] == [1]
    assert doc.metadata["pages_without_text"] == 2


@pytest.mark.skipif(not shutil.which("tesseract"), reason="needs tesseract")
def test_scanned_pdf_is_readable_with_ocr(samples: Path) -> None:
    pytest.importorskip("pytesseract")
    import pytesseract

    if "tur" not in pytesseract.get_languages():
        pytest.skip("needs tesseract Turkish data")
    from citewell.loaders import load_bytes

    path = samples / "pdf" / "taranmis.pdf"
    doc = load_bytes(path.read_bytes(), path.name, ocr=OcrOptions())
    assert doc.metadata["ocr_pages"] == [2, 3]
    assert "açık rıza aranmaz" in " ".join(doc.pages[1].text.split())


def test_limit_files_are_rejected(samples: Path) -> None:
    from citewell.loaders import load_bytes

    pdf, bomb = samples / "limits" / "uc-sayfa.pdf", samples / "limits" / "bomb.xlsx"
    with pytest.raises(LimitExceededError):
        load_bytes(pdf.read_bytes(), pdf.name, limits=LoadLimits(max_pages=2))
    with pytest.raises(LimitExceededError, match="zip bomb"):
        load_bytes(bomb.read_bytes(), bomb.name)


def test_a_missing_font_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mod = _script()
    mod.FONT_CANDIDATES = []
    assert mod.main([str(tmp_path / "x")]) == 1
    assert "--font" in capsys.readouterr().err
    assert mod.find_font("/does/not/exist.ttf") is None
