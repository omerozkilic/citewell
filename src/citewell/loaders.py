"""Document loaders: turn files into page-aware text.

Supported formats: PDF, Markdown, plain text, HTML and (optionally) DOCX.
Each loader returns :class:`~citewell.models.Page` objects so that chunks never
cross a page boundary and citations can point at an exact page.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import zipfile
from collections.abc import Callable, Iterable, Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar, NamedTuple

from citewell.models import LoadedDocument, Page
from citewell.ocr import OcrOptions, OcrSession, OcrUnavailableError
from citewell.text import clean_text, reflow

log = logging.getLogger(__name__)

SUPPORTED_SUFFIXES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".text": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


class UnsupportedFormatError(ValueError):
    pass


class LimitExceededError(UnsupportedFormatError):
    """A document is larger or more compressed than the configured safety limits."""


class LoadLimits(NamedTuple):
    """Safety limits against decompression bombs and huge inputs (0 disables a limit)."""

    max_pages: int = 5000
    max_unpacked_bytes: int = 200 * 1024 * 1024
    max_zip_ratio: int = 200


DEFAULT_LIMITS = LoadLimits()


def _check_zip(data: bytes, limits: LoadLimits) -> None:
    """Reject DOCX (zip) files that would unpack to an unreasonable size."""
    try:
        infos = zipfile.ZipFile(io.BytesIO(data)).infolist()
    except zipfile.BadZipFile as exc:
        raise UnsupportedFormatError("not a valid DOCX file") from exc
    unpacked = sum(i.file_size for i in infos)
    if limits.max_unpacked_bytes and unpacked > limits.max_unpacked_bytes:
        mb, cap = unpacked // (1024 * 1024), limits.max_unpacked_bytes // (1024 * 1024)
        raise LimitExceededError(f"DOCX unpacks to {mb} MB, over the {cap} MB limit")
    if limits.max_zip_ratio and unpacked > 10 * 1024 * 1024 and unpacked > len(data) * limits.max_zip_ratio:
        raise LimitExceededError(
            f"DOCX compression ratio exceeds {limits.max_zip_ratio}:1 (possible zip bomb)"
        )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    # Windows-1254 is the legacy Turkish code page; latin-1 never fails.
    try:
        return data.decode("cp1254")
    except UnicodeDecodeError:
        return data.decode("latin-1")


# --------------------------------------------------------------------------- PDF


def table_to_markdown(rows: list[list[str | None]]) -> str:
    """Render extracted table rows as Markdown; ``""`` for anything that is not a real table."""
    cleaned = [[" ".join(clean_text(c or "").split()).replace("|", "\\|") for c in row] for row in rows]
    cleaned = [r for r in cleaned if any(r)]
    width = max((len(r) for r in cleaned), default=0)
    if len(cleaned) < 2 or width < 2:  # one row or one column is layout, not a table
        return ""
    lines = ["| " + " | ".join(r + [""] * (width - len(r))) + " |" for r in cleaned]
    lines.insert(1, "|" + " --- |" * width)
    return "\n".join(lines)


def _prose(page: Any, top: float, bottom: float) -> str:
    left, page_top, right, page_bottom = page.bbox
    top, bottom = max(top, page_top), min(bottom, page_bottom)
    if bottom - top < 1:
        return ""
    return reflow(clean_text(page.crop((left, top, right, bottom)).extract_text() or ""))


def _page_text_with_tables(page: Any) -> str | None:
    """Page text with ruled tables as Markdown rows in reading order; ``None`` if it has no table."""
    found = []
    for table in page.find_tables():
        markdown = table_to_markdown(table.extract())
        if markdown:
            found.append((table.bbox, markdown))
    if not found:
        return None
    parts: list[str] = []
    cursor = page.bbox[1]
    for bbox, markdown in sorted(found, key=lambda item: item[0][1]):
        parts += [_prose(page, cursor, bbox[1]), markdown]
        cursor = max(cursor, bbox[3])
    parts.append(_prose(page, cursor, page.bbox[3]))
    return "\n\n".join(p for p in parts if p)


def load_pdf(
    data: bytes,
    limits: LoadLimits = DEFAULT_LIMITS,
    tables: bool = False,
    ocr: OcrOptions | None = None,
) -> tuple[list[Page], dict[str, str]]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if limits.max_pages and len(reader.pages) > limits.max_pages:
        raise LimitExceededError(f"PDF has {len(reader.pages)} pages, over the {limits.max_pages} page limit")
    plumber = None
    if tables:
        try:
            import pdfplumber
        except ImportError as exc:
            raise UnsupportedFormatError(
                "PDF table extraction requires: pip install 'citewell[tables]'"
            ) from exc
        plumber = pdfplumber.open(io.BytesIO(data))
    labels = _page_labels(reader)
    pages: list[Page] = []
    session: OcrSession | None = None
    ocr_budget = ocr.max_pages if ocr and ocr.max_pages else None
    try:
        for i, page in enumerate(reader.pages, start=1):
            text: str | None = None
            if plumber is not None:
                try:
                    text = _page_text_with_tables(plumber.pages[i - 1])
                except Exception as exc:  # fall back to the plain text of this page
                    log.warning("tables on page %s could not be extracted: %s", i, exc)
            if text is None:
                try:
                    text = reflow(clean_text(page.extract_text() or ""))
                except Exception as exc:  # pragma: no cover - malformed PDFs
                    log.warning("page %s could not be extracted: %s", i, exc)
                    text = ""
            recognised = False
            if ocr is not None and not text.strip() and (ocr_budget is None or ocr_budget > 0):
                try:
                    session = session or OcrSession(data, ocr)
                    text = reflow(clean_text(session.page_text(i - 1)))
                except OcrUnavailableError as exc:
                    raise UnsupportedFormatError(f"OCR is enabled but unavailable: {exc}") from exc
                recognised = bool(text.strip())
                if ocr_budget is not None:
                    ocr_budget -= 1
            label = labels[i - 1] if labels and i - 1 < len(labels) else None
            pages.append(Page(number=i, text=text, label=label, ocr=recognised))
    finally:
        if plumber is not None:
            plumber.close()
        if session is not None:
            session.close()
    meta: dict[str, str] = {}
    if reader.metadata:
        if reader.metadata.title:
            meta["title"] = str(reader.metadata.title)
        if reader.metadata.author:
            meta["author"] = str(reader.metadata.author)
    return pages, meta


def _page_labels(reader: Any) -> list[str] | None:
    """Printed page labels (/PageLabels), or None when they are just 1, 2, 3 …"""
    try:
        labels = [str(x) for x in reader.page_labels]
    except Exception:  # pragma: no cover - malformed label trees
        return None
    if not labels or all(lbl == str(i) for i, lbl in enumerate(labels, start=1)):
        return None
    return [lbl.strip() or str(i) for i, lbl in enumerate(labels, start=1)]


# ---------------------------------------------------------------------- Markdown

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_FRONT_MATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def load_markdown(text: str) -> tuple[list[Page], dict[str, str]]:
    """Split Markdown by headings; each section keeps its heading path."""
    meta: dict[str, str] = {}
    text = _FRONT_MATTER_RE.sub("", text)
    stack: list[tuple[int, str]] = []
    sections: list[Page] = []
    buf: list[str] = []
    in_code = False

    def flush() -> None:
        body = clean_text("\n".join(buf))
        if body:
            sections.append(Page(number=None, text=body, section=" > ".join(t for _, t in stack) or None))
        buf.clear()

    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        m = None if in_code else _HEADING_RE.match(line)
        if m:
            flush()
            level, title = len(m.group(1)), m.group(2).strip()
            if level == 1 and "title" not in meta:
                meta["title"] = title
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            buf.append(title)
        else:
            buf.append(line)
    flush()
    return sections, meta


# -------------------------------------------------------------------------- text


def load_text(text: str) -> tuple[list[Page], dict[str, str]]:
    """Plain text. Form feeds (``\\f``, as emitted by ``pdftotext``) mark pages."""
    if "\f" in text:
        pages = [Page(number=i, text=clean_text(part)) for i, part in enumerate(text.split("\f"), start=1)]
        return [p for p in pages if p.text], {}
    return [Page(number=None, text=clean_text(text))], {}


# -------------------------------------------------------------------------- HTML


class _HTMLText(HTMLParser):
    _SKIP: ClassVar[set[str]] = {"script", "style", "noscript", "template", "svg"}
    _BLOCK: ClassVar[set[str]] = {
        "p",
        "div",
        "br",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title: str | None = None
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self._BLOCK:
            self.parts.append("\n\n" if tag.startswith("h") or tag == "p" else "\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title = (self.title or "") + data.strip()
        elif not self._skip:
            self.parts.append(data)


def load_html(text: str) -> tuple[list[Page], dict[str, str]]:
    parser = _HTMLText()
    parser.feed(text)
    meta = {"title": parser.title} if parser.title else {}
    return [Page(number=None, text=clean_text("".join(parser.parts)))], meta


# -------------------------------------------------------------------------- DOCX


def load_docx(data: bytes, limits: LoadLimits = DEFAULT_LIMITS) -> tuple[list[Page], dict[str, str]]:
    _check_zip(data, limits)
    try:
        import docx
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise UnsupportedFormatError("DOCX support requires: pip install 'citewell[docx]'") from exc
    document = docx.Document(io.BytesIO(data))
    sections: list[Page] = []
    heading: str | None = None
    buf: list[str] = []
    for para in document.paragraphs:
        style = (para.style.name or "").lower() if para.style is not None else ""
        if style.startswith("heading") and para.text.strip():
            if buf:
                sections.append(Page(number=None, text=clean_text("\n".join(buf)), section=heading))
                buf = []
            heading = para.text.strip()
        buf.append(para.text)
    if buf:
        sections.append(Page(number=None, text=clean_text("\n".join(buf)), section=heading))
    meta = {"title": document.core_properties.title} if document.core_properties.title else {}
    return [s for s in sections if s.text], meta


# ------------------------------------------------------------------------ public

_Loader = Callable[[bytes, LoadLimits], tuple[list[Page], dict[str, str]]]

_LOADERS: dict[str, _Loader] = {
    "application/pdf": load_pdf,
    "text/markdown": lambda b, _l: load_markdown(_decode(b)),
    "text/plain": lambda b, _l: load_text(_decode(b)),
    "text/html": lambda b, _l: load_html(_decode(b)),
    SUPPORTED_SUFFIXES[".docx"]: load_docx,
}


def detect_mime(name: str) -> str:
    suffix = Path(name).suffix.lower()
    try:
        return SUPPORTED_SUFFIXES[suffix]
    except KeyError as exc:
        raise UnsupportedFormatError(f"unsupported file type: {suffix or name}") from exc


def load_bytes(
    data: bytes,
    source: str,
    mime: str | None = None,
    limits: LoadLimits = DEFAULT_LIMITS,
    pdf_tables: bool = False,
    ocr: OcrOptions | None = None,
) -> LoadedDocument:
    mime = mime or detect_mime(source)
    if mime == "application/pdf":
        pages, meta = load_pdf(data, limits, tables=pdf_tables, ocr=ocr)
    else:
        pages, meta = _LOADERS[mime](data, limits)
    title = meta.pop("title", None) or Path(source).stem.replace("_", " ").replace("-", " ")
    with_text = [p for p in pages if p.text.strip()]
    metadata: dict[str, Any] = dict(meta)
    if mime == "application/pdf":
        # Pages without a text layer are usually scanned images (see CITEWELL_OCR).
        metadata["total_pages"] = len(pages)
        metadata["pages_without_text"] = len(pages) - len(with_text)
        if ocr_pages := [p.number for p in with_text if p.ocr]:
            metadata["ocr_pages"] = ocr_pages
    return LoadedDocument(
        source=source,
        title=title,
        mime=mime,
        sha256=sha256_bytes(data),
        pages=with_text,
        metadata=metadata,
    )


def load_file(path: Path, source: str | None = None) -> LoadedDocument:
    return load_bytes(path.read_bytes(), source or path.name)


def iter_files(paths: Iterable[Path], recursive: bool = True) -> Iterator[tuple[Path, str]]:
    """Yield ``(path, source)`` pairs. ``source`` is relative to the given root."""
    for root in paths:
        root = root.expanduser()
        if root.is_file():
            if root.suffix.lower() in SUPPORTED_SUFFIXES:
                yield root, root.name
            continue
        if not root.is_dir():
            raise FileNotFoundError(root)
        pattern = "**/*" if recursive else "*"
        for path in sorted(root.glob(pattern)):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            rel = path.relative_to(root)
            if any(part.startswith(".") for part in rel.parts):
                continue
            yield path, rel.as_posix()
