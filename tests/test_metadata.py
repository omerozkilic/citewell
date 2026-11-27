"""Author / date extraction in the loaders and the SearchFilters model (no database)."""

from __future__ import annotations

import io
from datetime import UTC, date, datetime
from email.message import EmailMessage
from typing import Any

import pytest
from pydantic import ValidationError

from citewell.loaders import iso_date, load_bytes
from citewell.models import SearchFilters, normalise_tags

from .test_extra_loaders import _slide, _zip

CORE = (
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/">'
    "<dc:title>Sunum</dc:title><dc:creator>Ayşe Yılmaz</dc:creator>"
    "<dcterms:created>{created}</dcterms:created></cp:coreProperties>"
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (datetime(2024, 3, 15, 12, 0, tzinfo=UTC), "2024-03-15"),
        (date(2020, 1, 2), "2020-01-02"),
        ("2023-07-01T10:00:00Z", "2023-07-01"),
        ("D:20240315120000+03'00'", "2024-03-15"),
        ("20240315", "2024-03-15"),
        ("2023-02-30", None),  # not a calendar day
        ("yesterday", None),
        ("", None),
        (None, None),
        (42, None),
    ],
)
def test_iso_date(value: object, expected: str | None) -> None:
    assert iso_date(value) == expected


def test_pptx_core_properties_give_author_and_date() -> None:
    data = _zip(
        {
            "ppt/slides/slide1.xml": _slide("Merhaba"),
            "docProps/core.xml": CORE.format(created="2024-05-06T08:00:00Z"),
        }
    )
    doc = load_bytes(data, "sunum.pptx")
    assert (doc.title, doc.metadata["author"], doc.metadata["date"]) == ("Sunum", "Ayşe Yılmaz", "2024-05-06")


def test_core_properties_without_author_or_valid_date() -> None:
    data = _zip(
        {
            "ppt/slides/slide1.xml": _slide("Merhaba"),
            "docProps/core.xml": CORE.format(created="not a date").replace(
                "<dc:creator>Ayşe Yılmaz</dc:creator>", ""
            ),
        }
    )
    doc = load_bytes(data, "sunum.pptx")
    assert "author" not in doc.metadata and "date" not in doc.metadata


def test_docx_author_and_creation_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stand-in for python-docx (an optional extra that CI does not install)."""
    import sys
    import types

    class Para:
        style = None
        text = "Yıllık izin yönergesi"

    class Props:
        title = None
        author = "Mehmet Kaya"
        created = datetime(2022, 9, 1, 10, 0)

    class Document:
        def __init__(self) -> None:
            self.paragraphs = [Para()]
            self.core_properties = Props()

    fake = types.ModuleType("docx")
    fake.Document = lambda _stream: Document()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "docx", fake)
    doc = load_bytes(_zip({"word/document.xml": "<w/>"}), "yonerge.docx")
    assert doc.metadata["author"] == "Mehmet Kaya" and doc.metadata["date"] == "2022-09-01"


def _pdf(**info: str) -> bytes:
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "Yillik izin yonergesi")
    c.save()
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(buf.getvalue())))
    writer.add_metadata(info)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_pdf_author_and_creation_date() -> None:
    doc = load_bytes(_pdf(**{"/Author": "Zeynep Arslan", "/CreationDate": "D:20240315120000Z"}), "r.pdf")
    assert doc.metadata["author"] == "Zeynep Arslan" and doc.metadata["date"] == "2024-03-15"


def test_pdf_with_an_unreadable_creation_date_still_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    from pypdf import DocumentInformation

    def boom(_: Any) -> None:
        raise ValueError("bad date")

    monkeypatch.setattr(DocumentInformation, "creation_date", property(boom))
    doc = load_bytes(_pdf(**{"/Author": "A. Yazar"}), "r.pdf")
    assert doc.metadata["author"] == "A. Yazar" and "date" not in doc.metadata


def test_eml_sender_and_date() -> None:
    msg = EmailMessage()
    msg["Subject"] = "İzin"
    msg["From"] = "Ayşe Yılmaz <ayse@example.com>"
    msg["Date"] = "Mon, 03 Nov 2025 09:00:00 +0300"
    msg.set_content("Merhaba")
    doc = load_bytes(msg.as_bytes(), "a.eml")
    assert doc.metadata["author"] == "Ayşe Yılmaz <ayse@example.com>" and doc.metadata["date"] == "2025-11-03"


def test_eml_with_a_broken_date_keeps_the_author() -> None:
    msg = EmailMessage()
    msg["From"] = "x@example.com"
    msg["Date"] = "sometime last week"
    msg.set_content("Merhaba")
    doc = load_bytes(msg.as_bytes(), "b.eml")
    assert doc.metadata["author"] == "x@example.com" and "date" not in doc.metadata


def test_search_filters_normalise_and_validate() -> None:
    f = SearchFilters(
        file_types=[".PDF", " docx ", "pdf", ""], tags=[" İK ", "ik", "Politika"], author=" Ayşe "
    )
    assert f.file_types == ["docx", "pdf"]
    assert f.tags == ["ik", "politika"]  # Turkish-aware lower-casing, de-duplicated
    assert not f.is_empty()
    assert SearchFilters().is_empty()
    assert not SearchFilters(date_to=date(2024, 1, 1)).is_empty()
    with pytest.raises(ValidationError, match="invalid file type"):
        SearchFilters(file_types=["p d f"])
    assert normalise_tags(["", "  "]) == []
