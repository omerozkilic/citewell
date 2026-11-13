# ruff: noqa: E501  (embedded XML and the printed guide are long lines)
"""Generate small sample files for trying Citewell's loaders by hand.

    uv run python scripts/make_sample_files.py ./smoke-files
    uv run python scripts/make_sample_files.py ./smoke-files --font /path/to/Arial.ttf

Creates, under the output folder (all content is fictional, in Turkish):

    formats/  sunum.pptx  butce.xlsx  personel.csv  eski-kayit.csv  kitap.epub  iade.eml
    pdf/      tarife-tablolu.pdf  (a ruled table: try CITEWELL_PDF_TABLES=true)
              taranmis.pdf        (page 1 has text, pages 2-3 are images: try CITEWELL_OCR=auto)
    limits/   uc-sayfa.pdf  bomb.xlsx   (to see the page limit and the zip-bomb guard reject files)

Then it prints questions to ask and where each answer must come from. The scanned and table PDFs
need a TrueType font with Turkish letters; the script looks for DejaVu, Arial or Liberation and
otherwise asks for ``--font``.
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from email.message import EmailMessage
from pathlib import Path
from xml.sax.saxutils import escape

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def find_font(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit if Path(explicit).is_file() else None
    return next((p for p in FONT_CANDIDATES if Path(p).is_file()), None)


def _zip(path: Path, files: dict[str, str | bytes], stored_first: str | None = None) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        if stored_first:
            z.writestr(zipfile.ZipInfo(stored_first), files[stored_first], zipfile.ZIP_STORED)
        for name, content in files.items():
            if name != stored_first:
                z.writestr(name, content)


# ------------------------------------------------------------------------ formats


def make_pptx(path: Path) -> None:
    slides = [
        ["Yıllık Hedefler", "2026 hedefi: müşteri memnuniyet puanını 4,6'ya çıkarmak."],
        [
            "Bütçe Dağılımı",
            "Eğitim bütçesi kişi başı 15.000 TL'dir.",
            "Yazılım lisansları için 2,4 milyon TL ayrıldı.",
        ],
        ["Takvim", "Yeni ofis taşınması 15 Mart tarihinde yapılacaktır."],
    ]
    files: dict[str, str | bytes] = {}
    for n, lines in enumerate(slides, 1):
        body = "".join(f"<a:p><a:r><a:t>{escape(t)}</a:t></a:r></a:p>" for t in lines)
        files[f"ppt/slides/slide{n}.xml"] = (
            f'<p:sld xmlns:a="{A}" xmlns:p="{P}"><p:cSld><p:spTree><p:sp><p:txBody>{body}'
            "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
        )
    ids = "".join(f'<p:sldId id="{255 + n}" r:id="rId{n}"/>' for n in range(1, len(slides) + 1))
    files["ppt/presentation.xml"] = (
        f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldIdLst>{ids}</p:sldIdLst></p:presentation>'
    )
    rels = "".join(
        f'<Relationship Id="rId{n}" Target="slides/slide{n}.xml" Type="x"/>'
        for n in range(1, len(slides) + 1)
    )
    files["ppt/_rels/presentation.xml.rels"] = f'<Relationships xmlns="{PKG}">{rels}</Relationships>'
    files["docProps/core.xml"] = (
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Defne Yazılım 2026 Planı</dc:title></cp:coreProperties>'
    )
    _zip(path, files)


def _sheet_xml(rows: list[list[str | int]]) -> str:
    out = []
    for row in rows:
        cells = "".join(
            f"<c><v>{c}</v></c>"
            if isinstance(c, int)
            else f'<c t="inlineStr"><is><t>{escape(c)}</t></is></c>'
            for c in row
        )
        out.append(f"<row>{cells}</row>")
    return f'<worksheet xmlns="{S}"><sheetData>{"".join(out)}</sheetData></worksheet>'


def make_xlsx(path: Path) -> None:
    sheets = [
        (
            "Personel",
            [
                ["Ad", "Departman", "Şehir"],
                ["Ayşe Yılmaz", "İnsan Kaynakları", "Ankara"],
                ["Mehmet Demir", "Finans", "İzmir"],
            ],
            False,
        ),
        ("Bütçe 2026", [["Kalem", "Tutar"], ["Eğitim", 150000], ["Seyahat", 90000]], False),
        ("Gizli", [["Bu sayfa gizlidir: maaş tablosu"]], True),
    ]
    entries = "".join(
        f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"'
        + (' state="hidden"' if hidden else "")
        + "/>"
        for i, (name, _, hidden) in enumerate(sheets, 1)
    )
    files: dict[str, str | bytes] = {
        "xl/workbook.xml": f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets>{entries}</sheets></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{PKG}">'
        + "".join(
            f'<Relationship Id="rId{i}" Target="worksheets/sheet{i}.xml" Type="x"/>'
            for i in range(1, len(sheets) + 1)
        )
        + "</Relationships>",
    }
    for i, (_, rows, _) in enumerate(sheets, 1):
        files[f"xl/worksheets/sheet{i}.xml"] = _sheet_xml(rows)
    _zip(path, files)


def make_csv(folder: Path) -> None:
    (folder / "personel.csv").write_text(
        "ad;departman;şehir\nZeynep Kaya;Hukuk;Bursa\nCan Aydın;Yazılım;İstanbul\n",
        encoding="utf-8",
    )
    # Older Turkish exports (Excel on Windows) are cp1254, not UTF-8.
    (folder / "eski-kayit.csv").write_bytes("ürün;adet\nKalem;12\nDefter;30\nÇanta;5\n".encode("cp1254"))


def make_epub(path: Path) -> None:
    chapters = [
        ("Giriş", "Bu el kitabı yeni çalışanlar içindir."),
        ("Güvenlik", "Şifreler en az 14 karakter olmalıdır. Parola yöneticisi kullanmak zorunludur."),
    ]
    manifest = "".join(
        f'<item id="c{i}" href="ch{i}.xhtml" media-type="application/xhtml+xml"/>' for i in range(1, 3)
    )
    spine = "".join(f'<itemref idref="c{i}"/>' for i in range(1, 3))
    files: dict[str, str | bytes] = {
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
        '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        "OEBPS/content.opf": '<package xmlns="http://www.idpf.org/2007/opf" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<metadata><dc:title>Çalışan Kitabı</dc:title></metadata><manifest>{manifest}</manifest>"
        f"<spine>{spine}</spine></package>",
    }
    for i, (title, text) in enumerate(chapters, 1):
        files[f"OEBPS/ch{i}.xhtml"] = (
            f"<html><head><title>{escape(title)}</title></head><body><h1>{escape(title)}</h1>"
            f"<p>{escape(text)}</p></body></html>"
        )
    _zip(path, files, stored_first="mimetype")


def make_eml(path: Path) -> None:
    msg = EmailMessage()
    msg["Subject"] = "Seyahat masrafı iadesi"
    msg["From"] = "muhasebe@example.com"
    msg["To"] = "ayse@example.com"
    msg["Date"] = "Mon, 03 Nov 2025 09:00:00 +0300"
    msg.set_content("Merhaba,\n\nSeyahat masrafları fatura ile iade edilir. Beyan süresi 30 gündür.")
    msg.add_attachment(
        b"GIZLI-EK-ICERIK", maintype="application", subtype="octet-stream", filename="gizli.bin"
    )
    path.write_bytes(msg.as_bytes())


# --------------------------------------------------------------------------- PDFs


def make_table_pdf(path: Path, font: str | None) -> bool:
    """Returns whether Turkish letters were used (needs a TrueType font)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Table, TableStyle

    name, turkish = "Helvetica", False
    if font and not font.lower().endswith(".ttc"):
        try:
            pdfmetrics.registerFont(TTFont("TRFont", font))
            name, turkish = "TRFont", True
        except Exception:  # unusable font: fall back to ASCII text
            pass
    t = (lambda s: s) if turkish else (lambda s: s.translate(str.maketrans("şğıöüçŞĞİÖÜÇ", "sgioucSGIOUC")))
    style = ParagraphStyle("n", parent=getSampleStyleSheet()["Normal"], fontName=name)
    rows = [
        ["Hizmet", "Ücret (TL)", "Süre"],
        ["Başvuru ücreti", "1500", "5 gün"],
        ["Yenileme ücreti", "900", "3 gün"],
        ["Acil işlem", "2500", "1 gün"],
    ]
    table = Table(
        [[t(c) for c in row] for row in rows],
        style=TableStyle(
            [("GRID", (0, 0), (-1, -1), 0.5, colors.black), ("FONTNAME", (0, 0), (-1, -1), name)]
        ),
    )
    flow = [
        Paragraph(t("Ücret tarifesi aşağıdaki gibidir."), style),
        table,
        Paragraph(t("Ücretler yılda bir güncellenir."), style),
        PageBreak(),
        Paragraph(t("Bu sayfada tablo yoktur. Yalnızca düz metin vardır."), style),
    ]
    SimpleDocTemplate(str(path), pagesize=A4).build(flow)
    return turkish


def make_scanned_pdf(path: Path, font: str) -> None:
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    pil_font = ImageFont.truetype(font, 44)

    def scan(lines: list[str]) -> Image.Image:
        image = Image.new("L", (1240, 400), 255)
        draw = ImageDraw.Draw(image)
        for i, line in enumerate(lines):
            draw.text((60, 60 + i * 80), line, font=pil_font, fill=0)
        return image

    c = canvas.Canvas(str(path), pagesize=A4)
    c.drawString(72, 750, "Birinci sayfa: bu sayfada gercek metin katmani var.")
    c.showPage()
    for lines in (
        ["Kişisel verilerin işlenmesinde", "açık rıza aranmaz. Madde 5"],
        ["Veri sorumlusu başvuruyu en geç", "otuz gün içinde sonuçlandırır."],
    ):
        c.drawImage(ImageReader(scan(lines)), 0, 400, 595, 190)
        c.showPage()
    c.save()


def make_limit_files(folder: Path) -> None:
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(folder / "uc-sayfa.pdf"))
    for i in range(1, 4):
        c.drawString(72, 750, f"Sayfa {i} deneme metni.")
        c.showPage()
    c.save()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xl/workbook.xml", b"0" * (60 * 1024 * 1024))  # 60 MB of zeros, ~60 KB zipped
    (folder / "bomb.xlsx").write_bytes(buf.getvalue())


# ---------------------------------------------------------------------------- main

GUIDE = """
Try these (collection names are examples):

  uv run citewell ingest {out}/formats -c fmt
  uv run citewell search "Eğitim bütçesi kaç TL" -c fmt -k 1      -> sunum.pptx, slide 2
  uv run citewell search "Ayşe Yılmaz hangi şehirde" -c fmt -k 1  -> butce.xlsx, sheet Personel
  uv run citewell search "Hukuk departmanında kim var" -c fmt -k 1 -> personel.csv (semicolon-separated)
  uv run citewell search "eğitim 150000 seyahat 90000" -c fmt -k 1 -> butce.xlsx, sheet Bütçe 2026
  uv run citewell search "şifre en az kaç karakter" -c fmt -k 1   -> kitap.epub, chapter Güvenlik
  uv run citewell search "seyahat masrafı süre" -c fmt -k 1       -> iade.eml, section "Seyahat masrafı iadesi"
  uv run citewell search "GIZLI-EK-ICERIK" -c fmt -k 5             -> no result contains it: attachments are not indexed
  uv run citewell search "Bu sayfa gizlidir maaş tablosu" -c fmt -k 5   -> no result contains "gizlidir": the sheet is hidden
  uv run citewell search "Çanta adet" -c fmt -k 1                  -> eski-kayit.csv (cp1254 is read correctly)

  uv run citewell ingest {out}/pdf/tarife-tablolu.pdf -c tablo-kapali --force
  CITEWELL_PDF_TABLES=true uv run citewell ingest {out}/pdf/tarife-tablolu.pdf -c tablo-acik --force
  uv run citewell search "başvuru ücreti 1500" -c tablo-acik -k 1   -> a '| Başvuru ücreti | 1500 | 5 gün |' row

  uv run citewell ingest {out}/pdf/taranmis.pdf -c ocr-kapali --force          -> warns: 2/3 pages have no text
  CITEWELL_OCR=auto uv run citewell ingest {out}/pdf/taranmis.pdf -c ocr-acik --force
  uv run citewell documents list -c ocr-acik                                  -> pages "3 (2 OCR)"
  uv run citewell search "açık rıza aranmaz" -c ocr-acik -k 1                 -> page 2

  CITEWELL_MAX_DOCUMENT_PAGES=2 uv run citewell ingest {out}/limits/uc-sayfa.pdf -c limits   -> error: over the 2 page limit
  uv run citewell ingest {out}/limits/bomb.xlsx -c limits                                    -> error: possible zip bomb
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("output", type=Path, help="Folder to create the files in.")
    ap.add_argument("--font", help="TrueType font with Turkish letters (for the scanned and table PDFs).")
    args = ap.parse_args(argv)

    out: Path = args.output
    formats, pdfs, limits = out / "formats", out / "pdf", out / "limits"
    for folder in (formats, pdfs, limits):
        folder.mkdir(parents=True, exist_ok=True)

    make_pptx(formats / "sunum.pptx")
    make_xlsx(formats / "butce.xlsx")
    make_csv(formats)
    make_epub(formats / "kitap.epub")
    make_eml(formats / "iade.eml")
    make_limit_files(limits)

    font = find_font(args.font)
    turkish = make_table_pdf(pdfs / "tarife-tablolu.pdf", font)
    if not turkish:
        print("note: no usable TrueType font found; the table PDF uses ASCII letters (pass --font to fix)")
    if font is None:
        print(
            "error: taranmis.pdf needs a TrueType font with Turkish letters. Pass --font /path/to/font.ttf "
            "(macOS: /System/Library/Fonts/Supplemental/Arial.ttf).",
            file=sys.stderr,
        )
        return 1
    make_scanned_pdf(pdfs / "taranmis.pdf", font)
    print(f"wrote sample files to {out}")
    print(GUIDE.format(out=out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
