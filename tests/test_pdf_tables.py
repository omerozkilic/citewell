"""Tables in PDFs rendered as Markdown rows (``CITEWELL_PDF_TABLES``)."""

from __future__ import annotations

import io
import logging
import sys

import pytest

from citewell.chunking import chunk_page
from citewell.doctor import check_pdf_tables
from citewell.loaders import UnsupportedFormatError, load_bytes, table_to_markdown

from .conftest import make_settings

pytest.importorskip("pdfplumber")
pytest.importorskip("reportlab")


def _pdf(*pages: list[object]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

    style = getSampleStyleSheet()["Normal"]
    grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)])
    flow: list[object] = []
    for n, page in enumerate(pages):
        if n:
            flow.append(PageBreak())
        for item in page:
            if isinstance(item, str):
                flow.append(Paragraph(item, style))
            else:
                flow.append(Table(item, style=grid))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4).build(flow)
    return buf.getvalue()


FEES = [
    ["Hizmet", "Ucret (TL)", "Sure"],
    ["Basvuru ucreti", "1500", "5 gun"],
    ["Yenileme ucreti", "900", "3 gun"],
]
PROSE = "Bu sayfada tablo yoktur. Sadece duz metin vardir."


def test_ruled_table_becomes_markdown_in_reading_order() -> None:
    data = _pdf(["Ucret tarifesi asagidaki gibidir.", FEES, "Ucretler yilda bir guncellenir."])
    text = load_bytes(data, "t.pdf", pdf_tables=True).pages[0].text
    assert text == (
        "Ucret tarifesi asagidaki gibidir.\n\n"
        "| Hizmet | Ucret (TL) | Sure |\n| --- | --- | --- |\n"
        "| Basvuru ucreti | 1500 | 5 gun |\n| Yenileme ucreti | 900 | 3 gun |\n\n"
        "Ucretler yilda bir guncellenir."
    )


def test_off_by_default_and_pages_without_tables_are_unchanged() -> None:
    data = _pdf(["Tarife.", FEES], [PROSE])
    plain = load_bytes(data, "t.pdf")
    tables = load_bytes(data, "t.pdf", pdf_tables=True)
    assert "|" not in plain.pages[0].text  # the default path is the old one
    assert "| Basvuru ucreti | 1500 | 5 gun |" in tables.pages[0].text
    assert plain.pages[1].text == tables.pages[1].text == PROSE  # no regression on table-free pages
    assert [p.number for p in tables.pages] == [1, 2]


def test_several_tables_on_one_page_keep_their_order() -> None:
    other = [["Kalem", "Tutar"], ["Egitim", "4000"]]
    data = _pdf(["Birinci.", FEES, "Ikinci.", other, "Son."])
    text = load_bytes(data, "t.pdf", pdf_tables=True).pages[0].text
    order = [text.index(s) for s in ("Birinci.", "Hizmet", "Ikinci.", "Kalem", "Son.")]
    assert order == sorted(order)
    assert "| Egitim | 4000 |" in text


def test_a_failure_on_one_page_falls_back_to_plain_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(_: object) -> str:
        raise RuntimeError("layout engine failed")

    monkeypatch.setattr("citewell.loaders._page_text_with_tables", broken)
    with caplog.at_level(logging.WARNING):
        doc = load_bytes(_pdf([PROSE]), "t.pdf", pdf_tables=True)
    assert doc.pages[0].text == PROSE
    assert "tables on page 1 could not be extracted" in caplog.text


def test_missing_pdfplumber_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    with pytest.raises(UnsupportedFormatError, match=r"citewell\[tables\]"):
        load_bytes(_pdf([PROSE]), "t.pdf", pdf_tables=True)


# ----------------------------------------------------------------- table_to_markdown


def test_markdown_escapes_pipes_collapses_whitespace_and_pads_ragged_rows() -> None:
    rows: list[list[str | None]] = [["Ad", "Not"], ["a | b", "iki\nsatir   bosluk"], ["tek"]]
    assert (
        table_to_markdown(rows) == "| Ad | Not |\n| --- | --- |\n| a \\| b | iki satir bosluk |\n| tek |  |"
    )


def test_none_cells_and_empty_rows_are_dropped() -> None:
    rows: list[list[str | None]] = [["A", None], [None, None], ["1", "2"]]
    assert table_to_markdown(rows) == "| A |  |\n| --- | --- |\n| 1 | 2 |"


@pytest.mark.parametrize("rows", [[], [["only", "header"]], [["a"], ["b"]], [[None, None], [None, None]]])
def test_layout_that_is_not_a_table_is_ignored(rows: list[list[str | None]]) -> None:
    assert table_to_markdown(rows) == ""


# ---------------------------------------------------------------------------- chunking


def test_chunks_split_between_table_rows_not_inside_them() -> None:
    rows = [f"| Kalem {i} | {i * 1000} TL | aciklama {i} |" for i in range(30)]
    text = "Tarife\n\n| Ad | Tutar | Not |\n| --- | --- | --- |\n" + "\n".join(rows)
    spans = chunk_page(text, chunk_size=200, overlap=0, min_size=20)
    assert len(spans) > 2
    for start, end in spans:
        for line in text[start:end].split("\n"):
            assert line == "" or line.startswith("|") or line == "Tarife"  # no row cut in half
            assert not line.startswith("|") or line.endswith("|")


# -------------------------------------------------------------------------------- doctor


def test_doctor_flags_missing_pdfplumber(monkeypatch: pytest.MonkeyPatch) -> None:
    assert check_pdf_tables(make_settings()) == []
    assert check_pdf_tables(make_settings(pdf_tables=True))[0].status == "ok"
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    check = check_pdf_tables(make_settings(pdf_tables=True))[0]
    assert check.status == "fail" and "citewell[tables]" in check.hint
