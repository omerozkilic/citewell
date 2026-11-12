"""EPUB, PPTX, XLSX, CSV and EML loaders (standard library only).

Same contract as the other loaders: they return ``Page`` objects whose text is exactly what is
indexed and quoted (ADR-0006). Where a format has real pages (PPTX slides) the page number is the
slide number; otherwise pages are logical units (EPUB chapters, XLSX sheets) identified by
``Page.section``.

Everything ZIP-based goes through the same decompression-bomb checks as DOCX, and XML with
entity declarations is rejected outright, so a hostile file cannot expand into gigabytes.
"""

from __future__ import annotations

import csv
import email
import email.policy
import io
import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from urllib.parse import unquote

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import fromstring as safe_fromstring

from citewell.loaders import (
    LimitExceededError,
    LoadLimits,
    UnsupportedFormatError,
    _decode,
    _HTMLText,
    check_zip,
)
from citewell.models import Page
from citewell.text import clean_text

_REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_SECTION_MAX = 120

Loaded = tuple[list[Page], dict[str, str]]


# ----------------------------------------------------------------------- helpers


def _xml(data: bytes, what: str) -> ET.Element:
    """Parse untrusted XML: DTDs (entity expansion, external entities) are refused."""
    try:
        root: ET.Element = safe_fromstring(data, forbid_dtd=True)
        return root
    except DefusedXmlException as exc:
        raise UnsupportedFormatError(f"{what}: unsafe XML is not supported ({type(exc).__name__})") from exc
    except ET.ParseError as exc:
        raise UnsupportedFormatError(f"{what} is not valid XML: {exc}") from exc


def _open_zip(data: bytes, limits: LoadLimits) -> zipfile.ZipFile:
    check_zip(data, limits)
    return zipfile.ZipFile(io.BytesIO(data))


def _read(zf: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        return zf.read(name)
    except KeyError:
        return None


def _resolve(base_dir: str, target: str) -> str:
    """Resolve a relationship target (possibly URL-encoded, possibly absolute) inside the archive."""
    target = unquote(target.split("#", 1)[0])
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(base_dir, target))


def _relationships(zf: zipfile.ZipFile, rels_path: str, base_dir: str) -> dict[str, str]:
    raw = _read(zf, rels_path)
    if raw is None:
        return {}
    out: dict[str, str] = {}
    for rel in _xml(raw, rels_path).iterfind(".//{*}Relationship"):
        rid, target = rel.get("Id"), rel.get("Target")
        if rid and target and rel.get("TargetMode") != "External":
            out[rid] = _resolve(base_dir, target)
    return out


def _core_title(zf: zipfile.ZipFile) -> dict[str, str]:
    raw = _read(zf, "docProps/core.xml")
    if raw is None:
        return {}
    try:
        node = _xml(raw, "docProps/core.xml").find("{*}title")
    except UnsupportedFormatError:
        return {}
    title = (node.text or "").strip() if node is not None else ""
    return {"title": title} if title else {}


def _short(line: str) -> str | None:
    line = line.strip()
    return line if 0 < len(line) <= _SECTION_MAX else None


def _check_count(n: int, limits: LoadLimits, what: str) -> None:
    if limits.max_pages and n > limits.max_pages:
        raise LimitExceededError(f"{what} has {n} parts, over the {limits.max_pages} limit")


# -------------------------------------------------------------------------- PPTX


def _slide_paths(zf: zipfile.ZipFile) -> list[str]:
    """Slide files in presentation order (falls back to numeric file order)."""
    ordered: list[str] = []
    pres = _read(zf, "ppt/presentation.xml")
    if pres is not None:
        rels = _relationships(zf, "ppt/_rels/presentation.xml.rels", "ppt")
        for sld in _xml(pres, "ppt/presentation.xml").iterfind(".//{*}sldId"):
            target = rels.get(sld.get(_REL_ID, ""))
            if target and target in zf.namelist():
                ordered.append(target)
    if ordered:
        return ordered
    found = [n for n in zf.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)]
    return sorted(found, key=lambda n: int(re.findall(r"\d+", n)[-1]))


def _paragraphs(root: ET.Element) -> list[str]:
    out: list[str] = []
    for para in root.iterfind(".//{*}p"):
        pieces: list[str] = []
        for node in para.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag == "t" and node.text:
                pieces.append(node.text)
            elif tag == "br":
                pieces.append("\n")
        line = "".join(pieces).strip()
        if line:
            out.append(line)
    return out


def load_pptx(data: bytes, limits: LoadLimits) -> Loaded:
    with _open_zip(data, limits) as zf:
        slides = _slide_paths(zf)
        _check_count(len(slides), limits, "presentation")
        pages: list[Page] = []
        for number, path in enumerate(slides, start=1):
            raw = _read(zf, path)
            if raw is None:
                continue
            lines = _paragraphs(_xml(raw, path))
            if lines:
                pages.append(Page(number=number, text=clean_text("\n".join(lines)), section=_short(lines[0])))
        return pages, _core_title(zf)


# -------------------------------------------------------------------------- XLSX


def _shared_strings(zf: zipfile.ZipFile) -> list[str]:
    raw = _read(zf, "xl/sharedStrings.xml")
    if raw is None:
        return []
    return [
        "".join(t.text or "" for t in si.iterfind(".//{*}t"))
        for si in _xml(raw, "sharedStrings").iterfind(".//{*}si")
    ]


def _cell_text(cell: ET.Element, strings: list[str]) -> str:
    kind = cell.get("t", "n")
    if kind == "inlineStr":
        return "".join(t.text or "" for t in cell.iterfind(".//{*}t")).strip()
    value = cell.findtext("{*}v") or ""
    if kind == "s":
        try:
            return strings[int(value)].strip()
        except (ValueError, IndexError):
            return ""
    if kind == "b":
        return "TRUE" if value == "1" else "FALSE"
    return value.strip()


def _sheet_files(zf: zipfile.ZipFile) -> list[tuple[str, str]]:
    """``(sheet name, file)`` for visible sheets, in workbook order."""
    book = _read(zf, "xl/workbook.xml")
    if book is None:
        raise UnsupportedFormatError("not a valid XLSX file (xl/workbook.xml is missing)")
    rels = _relationships(zf, "xl/_rels/workbook.xml.rels", "xl")
    out: list[tuple[str, str]] = []
    for sheet in _xml(book, "xl/workbook.xml").iterfind(".//{*}sheet"):
        if sheet.get("state") in ("hidden", "veryHidden"):
            continue  # hidden sheets are hidden on purpose
        target = rels.get(sheet.get(_REL_ID, ""))
        if target:
            out.append((sheet.get("name") or f"Sheet {len(out) + 1}", target))
    return out


def load_xlsx(data: bytes, limits: LoadLimits) -> Loaded:
    with _open_zip(data, limits) as zf:
        sheets = _sheet_files(zf)
        _check_count(len(sheets), limits, "workbook")
        strings = _shared_strings(zf)
        pages: list[Page] = []
        for name, path in sheets:
            raw = _read(zf, path)
            if raw is None:
                continue
            rows: list[str] = []
            for row in _xml(raw, path).iterfind(".//{*}row"):
                cells = [_cell_text(c, strings) for c in row.iterfind(".//{*}c")]
                line = " | ".join(c for c in cells if c)
                if line:
                    rows.append(line)
            if rows:
                pages.append(Page(number=None, text=clean_text("\n".join(rows)), section=name))
        return pages, _core_title(zf)


# --------------------------------------------------------------------------- CSV


def load_csv(data: bytes, limits: LoadLimits) -> Loaded:
    text = _decode(data)
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows: list[str] = []
    try:
        for record in csv.reader(io.StringIO(text), dialect):
            line = " | ".join(c.strip() for c in record if c.strip())
            if line:
                rows.append(line)
    except csv.Error as exc:
        raise UnsupportedFormatError(f"not a readable CSV file: {exc}") from exc
    return [Page(number=None, text=clean_text("\n".join(rows)))], {}


# -------------------------------------------------------------------------- EPUB


def load_epub(data: bytes, limits: LoadLimits) -> Loaded:
    with _open_zip(data, limits) as zf:
        container = _read(zf, "META-INF/container.xml")
        if container is None:
            raise UnsupportedFormatError("not a valid EPUB file (META-INF/container.xml is missing)")
        rootfile = _xml(container, "container.xml").find(".//{*}rootfile")
        opf_path = unquote(rootfile.get("full-path", "")) if rootfile is not None else ""
        opf_raw = _read(zf, opf_path) if opf_path else None
        if opf_raw is None:
            raise UnsupportedFormatError("not a valid EPUB file (package document not found)")
        opf = _xml(opf_raw, opf_path)
        base = posixpath.dirname(opf_path)
        manifest = {
            item.get("id", ""): (item.get("href", ""), item.get("media-type", ""))
            for item in opf.iterfind(".//{*}item")
        }
        spine = [ref.get("idref", "") for ref in opf.iterfind(".//{*}itemref")]
        _check_count(len(spine), limits, "EPUB")
        pages: list[Page] = []
        for idref in spine:
            href, media = manifest.get(idref, ("", ""))
            if not href or "html" not in media:
                continue
            raw = _read(zf, _resolve(base, href))
            if raw is None:
                continue
            parser = _HTMLText()
            parser.feed(_decode(raw))
            text = clean_text("".join(parser.parts))
            if text:
                section = parser.title or _short(text.split("\n", 1)[0])
                pages.append(Page(number=None, text=text, section=section))
        title_node = opf.find(".//{*}title")
        title = (title_node.text or "").strip() if title_node is not None else ""
        return pages, ({"title": title} if title else {})


# --------------------------------------------------------------------------- EML


def load_eml(data: bytes, limits: LoadLimits) -> Loaded:
    msg = email.message_from_bytes(data, policy=email.policy.default)
    subject = str(msg.get("subject", "") or "").strip()
    header_lines = [
        f"{label}: {value}"
        for label, key in (("Subject", "subject"), ("From", "from"), ("To", "to"), ("Date", "date"))
        if (value := str(msg.get(key, "") or "").strip())
    ]
    body = ""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is not None:
        try:
            content = str(part.get_content())
        except (LookupError, UnicodeError):  # unknown charset: fall back to raw bytes
            payload = part.get_payload(decode=True)
            content = _decode(payload if isinstance(payload, bytes) else b"")
        if part.get_content_type() == "text/html":
            parser = _HTMLText()
            parser.feed(content)
            content = "".join(parser.parts)
        body = content
    text = clean_text("\n".join(header_lines) + "\n\n" + body)
    return [Page(number=None, text=text, section=subject or None)], ({"title": subject} if subject else {})
