"""PPTX, XLSX, CSV, EPUB and EML loaders, tested with documents built in memory."""

from __future__ import annotations

import io
import zipfile
from email.message import EmailMessage
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from citewell.loaders import (
    SUPPORTED_SUFFIXES,
    LimitExceededError,
    LoadLimits,
    UnsupportedFormatError,
    iter_files,
    load_bytes,
)

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def _zip(files: dict[str, str | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            z.writestr(name, content)
    return buf.getvalue()


def _core(title: str) -> str:
    return (
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        f'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>{escape(title)}</dc:title></cp:coreProperties>'
    )


# ------------------------------------------------------------------------ PPTX


def _slide(*paragraphs: str) -> str:
    body = "".join(f"<a:p><a:r><a:t>{escape(p)}</a:t></a:r></a:p>" for p in paragraphs)
    return f'<p:sld xmlns:a="{A}" xmlns:p="{P}"><p:cSld><p:spTree><p:sp><p:txBody>{body}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>'


def _pptx(slides: dict[str, str], order: list[str] | None, title: str | None = None) -> bytes:
    files: dict[str, str | bytes] = {f"ppt/slides/{name}.xml": xml for name, xml in slides.items()}
    if order is not None:
        ids = "".join(f'<p:sldId id="{256 + i}" r:id="rId{i}"/>' for i, _ in enumerate(order, 1))
        files["ppt/presentation.xml"] = (
            f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>'
        )
        rels = "".join(
            f'<Relationship Id="rId{i}" Target="slides/{name}.xml" Type="x"/>'
            for i, name in enumerate(order, 1)
        )
        files["ppt/_rels/presentation.xml.rels"] = f'<Relationships xmlns="{PKG_REL}">{rels}</Relationships>'
    if title:
        files["docProps/core.xml"] = _core(title)
    return _zip(files)


def test_pptx_follows_presentation_order_and_numbers_slides() -> None:
    data = _pptx(
        {"slide1": _slide("Giriş", "Hoş geldiniz"), "slide2": _slide("Bütçe", "Yıllık bütçe 2025")},
        order=["slide2", "slide1"],
        title="Sunum",
    )
    doc = load_bytes(data, "sunum.pptx")
    assert doc.title == "Sunum"
    assert [(p.number, p.section) for p in doc.pages] == [(1, "Bütçe"), (2, "Giriş")]
    assert doc.pages[0].text == "Bütçe\nYıllık bütçe 2025"


def test_pptx_without_presentation_xml_falls_back_to_file_order_and_skips_empty_slides() -> None:
    slides = {"slide10": _slide("Onuncu"), "slide2": _slide("İkinci"), "slide3": _slide()}
    doc = load_bytes(_pptx(slides, order=None), "x.pptx")
    assert [p.text for p in doc.pages] == ["İkinci", "Onuncu"]
    assert [p.number for p in doc.pages] == [1, 3]  # numbers keep the slide position; slide3 is empty


def test_pptx_line_breaks_inside_a_paragraph() -> None:
    xml = f'<p:sld xmlns:a="{A}" xmlns:p="{P}"><a:p><a:r><a:t>Satır bir</a:t></a:r><a:br/><a:r><a:t>Satır iki</a:t></a:r></a:p></p:sld>'
    doc = load_bytes(_pptx({"slide1": xml}, order=["slide1"]), "x.pptx")
    assert doc.pages[0].text == "Satır bir\nSatır iki"


def test_pptx_long_first_line_is_not_used_as_section() -> None:
    doc = load_bytes(_pptx({"slide1": _slide("x" * 300)}, order=["slide1"]), "x.pptx")
    assert doc.pages[0].section is None


def test_pptx_slide_missing_from_archive_is_skipped() -> None:
    data = _pptx({"slide1": _slide("Var")}, order=["slide1", "slide9"])
    assert [p.text for p in load_bytes(data, "x.pptx").pages] == ["Var"]


# ------------------------------------------------------------------------ XLSX


def _xlsx(
    sheets: list[tuple[str, str, str]], shared: list[str] | None = None, hidden: set[str] | None = None
) -> bytes:
    """``sheets``: (name, file, sheetData rows xml)."""
    hidden = hidden or set()
    entries = "".join(
        f'<sheet name="{escape(n)}" sheetId="{i}" r:id="rId{i}"'
        + (' state="hidden"' if n in hidden else "")
        + "/>"
        for i, (n, _, _) in enumerate(sheets, 1)
    )
    files: dict[str, str | bytes] = {
        "xl/workbook.xml": f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets>{entries}</sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{PKG_REL}">'
        + "".join(
            f'<Relationship Id="rId{i}" Target="worksheets/{f}" Type="x"/>'
            for i, (_, f, _) in enumerate(sheets, 1)
        )
        + "</Relationships>",
    }
    for _, f, rows in sheets:
        files[f"xl/worksheets/{f}"] = f'<worksheet xmlns="{S}"><sheetData>{rows}</sheetData></worksheet>'
    if shared is not None:
        items = "".join(f"<si><r><t>{escape(s)}</t></r></si>" for s in shared)
        files["xl/sharedStrings.xml"] = f'<sst xmlns="{S}">{items}</sst>'
    return _zip(files)


def test_xlsx_sheets_become_sections_with_all_cell_types() -> None:
    rows = (
        '<row><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row>'
        '<row><c t="inlineStr"><is><t>Ankara</t></is></c><c><v>42</v></c><c t="b"><v>1</v></c><c t="b"><v>0</v></c></row>'
        '<row><c t="s"><v>99</v></c><c t="s"><v>x</v></c></row>'  # bad shared-string references are ignored
    )
    data = _xlsx([("Personel", "sheet1.xml", rows)], shared=["Ad", "Şehir"])
    doc = load_bytes(data, "liste.xlsx")
    assert len(doc.pages) == 1 and doc.pages[0].number is None
    assert doc.pages[0].section == "Personel"
    assert doc.pages[0].text == "Ad | Şehir\nAnkara | 42 | TRUE | FALSE"


def test_xlsx_skips_hidden_and_empty_sheets() -> None:
    sheets = [
        ("Açık", "a.xml", '<row><c t="inlineStr"><is><t>görünür</t></is></c></row>'),
        ("Gizli", "b.xml", '<row><c t="inlineStr"><is><t>gizli veri</t></is></c></row>'),
        ("Boş", "c.xml", "<row/>"),
    ]
    doc = load_bytes(_xlsx(sheets, hidden={"Gizli"}), "x.xlsx")
    assert [(p.section, p.text) for p in doc.pages] == [("Açık", "görünür")]


def test_xlsx_missing_workbook_is_reported() -> None:
    with pytest.raises(UnsupportedFormatError, match="workbook"):
        load_bytes(_zip({"foo.txt": "x"}), "x.xlsx")


def test_xlsx_sheet_file_missing_is_skipped() -> None:
    data = _zip(
        {
            "xl/workbook.xml": f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets><sheet name="A" r:id="rId1"/></sheets></workbook>',
            "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" Target="worksheets/none.xml"/></Relationships>',
        }
    )
    assert load_bytes(data, "x.xlsx").pages == []


# ------------------------------------------------------------------------- CSV


def test_csv_comma_and_semicolon_and_legacy_encoding() -> None:
    doc = load_bytes("ad,şehir\nAyşe,İzmir\n\nMehmet,Bursa\n".encode(), "a.csv")
    assert doc.pages[0].text == "ad | şehir\nAyşe | İzmir\nMehmet | Bursa"
    semi = load_bytes("ad;şehir\nÇağlar;Ankara\n".encode("cp1254"), "b.csv")  # Turkish Excel exports
    assert semi.pages[0].text == "ad | şehir\nÇağlar | Ankara"


def test_csv_quoted_fields_and_single_column() -> None:
    assert load_bytes(b'a,"b, c"\n', "q.csv").pages[0].text == "a | b, c"
    assert load_bytes("tek\nsütun\n".encode(), "s.csv").pages[0].text == "tek\nsütun"


def test_csv_with_a_huge_field_is_rejected() -> None:
    with pytest.raises(UnsupportedFormatError, match="CSV"):
        load_bytes(b"a,b\n" + b"x" * 200_000 + b",c\n", "big.csv")


# ------------------------------------------------------------------------ EPUB


def _epub(
    chapters: list[tuple[str, str, str]], extra: dict[str, str | bytes] | None = None, title: str = "Kitap"
) -> bytes:
    """``chapters``: (file name, <title>, body html)."""
    manifest = "".join(
        f'<item id="c{i}" href="text/{name}" media-type="application/xhtml+xml"/>'
        for i, (name, _, _) in enumerate(chapters)
    )
    manifest += '<item id="css" href="style.css" media-type="text/css"/>'
    spine = '<itemref idref="css"/>' + "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
    files: dict[str, str | bytes] = {
        "META-INF/container.xml": '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
        '<rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        "OEBPS/content.opf": f'<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<metadata><dc:title>{escape(title)}</dc:title></metadata><manifest>{manifest}</manifest><spine>{spine}</spine></package>",
    }
    for name, ctitle, body in chapters:
        files[f"OEBPS/text/{name}"] = f"<html><head><title>{ctitle}</title></head><body>{body}</body></html>"
    files.update(extra or {})
    return _zip(files)


def test_epub_chapters_follow_the_spine() -> None:
    data = _epub(
        [("b.xhtml", "İkinci Bölüm", "<p>Sonraki.</p>"), ("a.xhtml", "", "<h1>Giriş</h1><p>Önce.</p>")]
    )
    doc = load_bytes(data, "kitap.epub")
    assert doc.title == "Kitap"
    assert [p.section for p in doc.pages] == ["İkinci Bölüm", "Giriş"]
    assert doc.pages[0].text == "Sonraki." and all(p.number is None for p in doc.pages)


def test_epub_url_encoded_hrefs_and_missing_chapters() -> None:
    data = _epub([("bölüm bir.xhtml", "Bir", "<p>Metin</p>")])
    data = _zip(
        {n: (zipfile.ZipFile(io.BytesIO(data)).read(n)) for n in zipfile.ZipFile(io.BytesIO(data)).namelist()}
        | {
            "OEBPS/content.opf": zipfile.ZipFile(io.BytesIO(data))
            .read("OEBPS/content.opf")
            .replace(b"b\xc3\xb6l\xc3\xbcm bir", b"b%C3%B6l%C3%BCm%20bir")
        }
    )
    assert [p.text for p in load_bytes(data, "k.epub").pages] == ["Metin"]
    opf_only = _epub([("x.xhtml", "X", "<p>Y</p>")])
    z = zipfile.ZipFile(io.BytesIO(opf_only))
    rebuilt = _zip({n: z.read(n) for n in z.namelist() if not n.endswith("x.xhtml")})
    assert load_bytes(rebuilt, "k.epub").pages == []


def test_epub_structure_errors() -> None:
    with pytest.raises(UnsupportedFormatError, match="container"):
        load_bytes(_zip({"a": "b"}), "x.epub")
    no_opf = _zip(
        {
            "META-INF/container.xml": '<container><rootfiles><rootfile full-path="missing.opf"/></rootfiles></container>'
        }
    )
    with pytest.raises(UnsupportedFormatError, match="package document"):
        load_bytes(no_opf, "x.epub")


def test_epub_part_limit() -> None:
    data = _epub([("a.xhtml", "A", "<p>1</p>"), ("b.xhtml", "B", "<p>2</p>")])
    with pytest.raises(LimitExceededError):
        load_bytes(data, "k.epub", limits=LoadLimits(max_pages=1))


# ------------------------------------------------------------------------- EML


def test_eml_plain_text_keeps_headers_in_the_indexed_text() -> None:
    msg = EmailMessage()
    msg["Subject"] = "Yıllık izin onayı"
    msg["From"] = "ayse@example.com"
    msg["To"] = "ik@example.com"
    msg["Date"] = "Mon, 03 Nov 2025 09:00:00 +0300"
    msg.set_content("Merhaba,\n\nİzin talebiniz onaylandı.")
    doc = load_bytes(msg.as_bytes(), "izin.eml")
    assert doc.title == "Yıllık izin onayı"
    page = doc.pages[0]
    assert page.section == "Yıllık izin onayı" and page.number is None
    assert page.text.startswith("Subject: Yıllık izin onayı\nFrom: ayse@example.com")
    assert "İzin talebiniz onaylandı." in page.text


def test_eml_html_only_and_attachments_are_handled() -> None:
    msg = EmailMessage()
    msg["Subject"] = "Rapor"
    msg.set_content(
        "<html><body><p>Aylık <b>rapor</b> ektedir.</p><script>x()</script></body></html>", subtype="html"
    )
    msg.add_attachment(b"secret", maintype="application", subtype="octet-stream", filename="gizli.bin")
    text = load_bytes(msg.as_bytes(), "r.eml").pages[0].text
    assert "Aylık rapor ektedir." in text and "x()" not in text and "secret" not in text


def test_eml_prefers_the_plain_alternative() -> None:
    msg = EmailMessage()
    msg["Subject"] = "Alt"
    msg.set_content("düz metin")
    msg.add_alternative("<p>html metin</p>", subtype="html")
    text = load_bytes(msg.as_bytes(), "a.eml").pages[0].text
    assert "düz metin" in text and "html metin" not in text


def test_eml_without_body_or_subject() -> None:
    doc = load_bytes(b"From: a@example.com\n\n", "n.eml")
    assert doc.pages[0].section is None and doc.pages[0].text == "From: a@example.com"


def test_eml_with_unknown_charset_falls_back() -> None:
    raw = b"Subject: x\nContent-Type: text/plain; charset=no-such-charset\nContent-Transfer-Encoding: 8bit\n\ng\xc3\xbcn\xc3\xa7"
    assert "x" in load_bytes(raw, "u.eml").pages[0].text


# ------------------------------------------------------------------ cross-cutting


@pytest.mark.parametrize("suffix", [".pptx", ".xlsx", ".epub"])
def test_zip_documents_reject_bombs_and_garbage(suffix: str) -> None:
    bomb = _zip({"payload.xml": "0" * 5_000_000})
    with pytest.raises(LimitExceededError):
        load_bytes(bomb, f"b{suffix}", limits=LoadLimits(max_unpacked_bytes=1_000_000))
    with pytest.raises(UnsupportedFormatError):
        load_bytes(b"not a zip", f"g{suffix}")


@pytest.mark.parametrize(
    ("name", "files"),
    [
        ("x.pptx", {"ppt/presentation.xml": "<p:presentation/>"}),
        ("x.xlsx", {"xl/workbook.xml": "<workbook"}),
        ("x.epub", {"META-INF/container.xml": "<container"}),
    ],
)
def test_broken_xml_is_reported_not_crashed(name: str, files: dict[str, str | bytes]) -> None:
    with pytest.raises(UnsupportedFormatError, match=r"XML|workbook|container|slide"):
        load_bytes(_zip(files), name)


def test_xml_with_a_dtd_is_refused() -> None:
    evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><workbook>&a;</workbook>'
    with pytest.raises(UnsupportedFormatError, match="unsafe XML"):
        load_bytes(_zip({"xl/workbook.xml": evil}), "evil.xlsx")


def test_new_suffixes_are_discovered_when_ingesting_folders(tmp_path: Path) -> None:
    for name in ("a.pptx", "b.xlsx", "c.csv", "d.epub", "e.eml", "ignored.png"):
        (tmp_path / name).write_bytes(b"x")
    assert sorted(s for _, s in iter_files([tmp_path])) == ["a.pptx", "b.xlsx", "c.csv", "d.epub", "e.eml"]
    assert {".pptx", ".xlsx", ".csv", ".epub", ".eml"} <= set(SUPPORTED_SUFFIXES)
