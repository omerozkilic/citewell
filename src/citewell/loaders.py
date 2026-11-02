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
from collections.abc import Callable, Iterable, Iterator
from html.parser import HTMLParser
from pathlib import Path
from typing import ClassVar

from citewell.models import LoadedDocument, Page
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


def load_pdf(data: bytes) -> tuple[list[Page], dict[str, str]]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages: list[Page] = []
    for i, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except Exception as exc:  # pragma: no cover - malformed PDFs
            log.warning("page %s could not be extracted: %s", i, exc)
            raw = ""
        pages.append(Page(number=i, text=reflow(clean_text(raw))))
    meta: dict[str, str] = {}
    if reader.metadata:
        if reader.metadata.title:
            meta["title"] = str(reader.metadata.title)
        if reader.metadata.author:
            meta["author"] = str(reader.metadata.author)
    return pages, meta


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


def load_docx(data: bytes) -> tuple[list[Page], dict[str, str]]:
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

_Loader = Callable[[bytes], tuple[list[Page], dict[str, str]]]

_LOADERS: dict[str, _Loader] = {
    "application/pdf": load_pdf,
    "text/markdown": lambda b: load_markdown(_decode(b)),
    "text/plain": lambda b: load_text(_decode(b)),
    "text/html": lambda b: load_html(_decode(b)),
    SUPPORTED_SUFFIXES[".docx"]: load_docx,
}


def detect_mime(name: str) -> str:
    suffix = Path(name).suffix.lower()
    try:
        return SUPPORTED_SUFFIXES[suffix]
    except KeyError as exc:
        raise UnsupportedFormatError(f"unsupported file type: {suffix or name}") from exc


def load_bytes(data: bytes, source: str, mime: str | None = None) -> LoadedDocument:
    mime = mime or detect_mime(source)
    pages, meta = _LOADERS[mime](data)
    title = meta.pop("title", None) or Path(source).stem.replace("_", " ").replace("-", " ")
    return LoadedDocument(
        source=source,
        title=title,
        mime=mime,
        sha256=sha256_bytes(data),
        pages=[p for p in pages if p.text.strip()],
        metadata=meta,
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
