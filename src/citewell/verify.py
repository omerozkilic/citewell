"""Quote verification: does a quoted sentence really appear in the source?

Assistants paraphrase. ``verify_quote`` lets them check a direct quote before they
present it, and gives back the exact source wording (and its page) when the
quote is only close. Matching levels, strictest first:

* ``exact``       – the quote occurs verbatim (whitespace differences ignored);
* ``normalized``  – it occurs after Turkish-aware case folding and unifying
  typographic quotes, dashes and soft hyphens;
* ``ellipsis``    – a quote with ``…`` / ``...`` gaps whose parts occur in order
  on the same page/section;
* ``fuzzy``       – not found, but a passage is very similar (``verified=False``;
  the closest source text is returned so the quote can be corrected);
* ``not_found``.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from citewell.models import ChunkRecord, QuoteCheck, citation_label
from citewell.search import SearchRequest, SearchService
from citewell.store import NotFoundError, Store

MatchKind = Literal["exact", "normalized", "ellipsis", "fuzzy", "not_found"]

FUZZY_THRESHOLD = 0.82
_ELLIPSIS_RE = re.compile(r"\s*(?:…|\.\.\.|\[\s*…\s*\]|\[\.\.\.\]|\(\s*…\s*\)|\(\.\.\.\))\s*")
_CHAR_MAP = {
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "″": '"',
    "‘": "'", "’": "'", "‚": "'", "′": "'", "`": "'",
    "–": "-", "—": "-", "‒": "-", "−": "-", "‐": "-", "‑": "-",
    "­": "",  # soft hyphen
    "İ": "i", "I": "ı",  # Turkish casing
}  # fmt: skip


@dataclass(frozen=True, slots=True)
class Normalized:
    text: str
    index: tuple[int, ...]  # index[i] = position in the original string of text[i]


def normalize(text: str, fold: bool = True) -> Normalized:
    """Collapse whitespace (and, with ``fold``, case/typography), keeping an offset map."""
    text = unicodedata.normalize("NFC", text)
    out: list[str] = []
    index: list[int] = []
    pending_space = False
    for i, ch in enumerate(text):
        if ch.isspace():
            pending_space = bool(out)
            continue
        repl = (_CHAR_MAP.get(ch, ch.lower())) if fold else ch
        if not repl:
            continue
        if pending_space:
            out.append(" ")
            index.append(i)
            pending_space = False
        for r in repl:
            out.append(r)
            index.append(i)
    return Normalized("".join(out), tuple(index))


@dataclass(frozen=True, slots=True)
class PageText:
    """The text of one page (or Markdown section) rebuilt from its chunks."""

    document_id: int
    page: int | None
    section: str | None
    text: str
    chunks: tuple[ChunkRecord, ...]

    def chunk_at(self, offset: int) -> ChunkRecord:
        best = self.chunks[0]
        for c in self.chunks:
            if c.char_start <= offset:
                best = c
            if c.char_start <= offset < c.char_end:
                return c
        return best


def rebuild_pages(chunks: Iterable[ChunkRecord]) -> list[PageText]:
    """Reassemble page texts from (possibly overlapping) verbatim chunks."""
    groups: dict[tuple[int, int | None, str | None], list[ChunkRecord]] = {}
    for c in chunks:
        groups.setdefault((c.document_id, c.page, c.section), []).append(c)
    pages: list[PageText] = []
    for (doc_id, page, section), cs in groups.items():
        cs.sort(key=lambda c: (c.char_start, c.ord))
        buf = ""
        for c in cs:
            if c.char_start >= len(buf):
                buf += " " * (c.char_start - len(buf)) + c.text
            elif c.char_end > len(buf):
                buf += c.text[len(buf) - c.char_start :]
        pages.append(PageText(doc_id, page, section, buf, tuple(cs)))
    pages.sort(key=lambda p: (p.document_id, p.page if p.page is not None else -1, p.chunks[0].ord))
    return pages


@dataclass(frozen=True, slots=True)
class Match:
    kind: MatchKind
    similarity: float
    page: PageText | None = None
    start: int = 0  # offsets in page.text
    end: int = 0

    @property
    def source_text(self) -> str | None:
        return self.page.text[self.start : self.end] if self.page else None


def _find(needle: Normalized, hay: Normalized, from_: int = 0) -> tuple[int, int] | None:
    pos = hay.text.find(needle.text, from_)
    if pos < 0 or not needle.text:
        return None
    return pos, pos + len(needle.text)


def _span(hay: Normalized, start: int, end: int) -> tuple[int, int]:
    """Map a span of normalized text back to original offsets."""
    return hay.index[start], hay.index[end - 1] + 1


def match_in_page(quote: str, page: PageText) -> Match | None:
    """Strict levels only (exact / normalized / ellipsis)."""
    raw_q, raw_p = normalize(quote, fold=False), normalize(page.text, fold=False)
    hit = _find(raw_q, raw_p)
    if hit:
        return Match("exact", 1.0, page, *_span(raw_p, *hit))
    q, p = normalize(quote), normalize(page.text)
    hit = _find(q, p)
    if hit:
        return Match("normalized", 1.0, page, *_span(p, *hit))
    parts = [part for part in _ELLIPSIS_RE.split(quote) if part.strip()]
    if len(parts) > 1:
        spans: list[tuple[int, int]] = []
        pos = 0
        for part in parts:
            found = _find(normalize(part), p, pos)
            if not found:
                return None
            spans.append(found)
            pos = found[1]
        return Match("ellipsis", 1.0, page, *_span(p, spans[0][0], spans[-1][1]))
    return None


def fuzzy_in_page(quote: str, page: PageText) -> Match:
    """Closest window of ``page`` to ``quote`` by character similarity."""
    q, p = normalize(quote), normalize(page.text)
    if not q.text or not p.text:
        return Match("not_found", 0.0, page)
    n = len(q.text)
    starts = [0] + [m.end() for m in re.finditer(r"[\s(\"'-]", p.text)]
    best = (0.0, 0, min(n, len(p.text)))
    matcher = SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(q.text)
    for s in starts:
        for length in {n, int(n * 0.9), int(n * 1.1)}:
            e = min(len(p.text), s + max(1, length))
            matcher.set_seq1(p.text[s:e])
            if matcher.real_quick_ratio() <= best[0] or matcher.quick_ratio() <= best[0]:
                continue
            r = matcher.ratio()
            if r > best[0]:
                best = (r, s, e)
    ratio, s, e = best
    # Snap the window to whole words (and a directly following sentence mark).
    while e < len(p.text) and (p.text[e].isalnum() or p.text[e] in "'’"):
        e += 1
    if e < len(p.text) and p.text[e] in ".!?…;:":
        e += 1
    start, end = _span(p, s, e)
    kind: MatchKind = "fuzzy" if ratio >= FUZZY_THRESHOLD else "not_found"
    return Match(kind, round(ratio, 4), page, start, end)


def best_match(quote: str, pages: Sequence[PageText]) -> Match:
    """Strict match on any page if possible, otherwise the most similar passage."""
    for page in pages:
        m = match_in_page(quote, page)
        if m:
            return m
    best = Match("not_found", 0.0)
    for page in pages:
        m = fuzzy_in_page(quote, page)
        if m.similarity > best.similarity:
            best = m
    return best


# --------------------------------------------------------------------------- service

_NOTES: dict[MatchKind, str] = {
    "exact": "Quote found verbatim in the source.",
    "normalized": "Quote found; it differs from the source only in letter case, quote marks or dashes.",
    "ellipsis": "All parts of the quote were found, in order, on the same page.",
    "fuzzy": (
        "Not a verbatim quote. The closest source passage is in source_text: quote that wording "
        "instead, or present it as a paraphrase without quotation marks."
    ),
    "not_found": (
        "The quote was not found in the searched documents. Do not present it as a quotation; "
        "search again or rephrase without quotation marks."
    ),
}

MAX_FUZZY_PAGES = 8
MIN_QUOTE_CHARS = 8


class QuoteVerifier:
    """Finds where a quote occurs. Strict matching scans whole documents; the (slower)
    fuzzy fallback only looks at the most relevant pages."""

    def __init__(self, store: Store, search: SearchService):
        self.store = store
        self.search = search

    def _pages_for_documents(self, doc_ids: Iterable[int]) -> list[PageText]:
        pages: list[PageText] = []
        for doc_id in dict.fromkeys(doc_ids):
            pages.extend(rebuild_pages(self.store.document_chunks(doc_id)))
        return pages

    def _hit_pages(
        self, quote: str, collections: Sequence[str] | None, source: str | None
    ) -> list[tuple[int, int | None, str | None]]:
        resp = self.search.search(
            SearchRequest(
                query=quote[:2000],
                top_k=MAX_FUZZY_PAGES,
                mode="hybrid",
                collections=list(collections) if collections else ["*"],
                source_prefix=source,
            )
        )
        return [(h.document_id, h.page, h.section) for h in resp.hits if source is None or h.source == source]

    def verify(
        self,
        quote: str,
        chunk_id: str | None = None,
        source: str | None = None,
        collections: Sequence[str] | None = None,
    ) -> QuoteCheck:
        quote = quote.strip().strip('"“”«»').strip()
        if len(quote) < MIN_QUOTE_CHARS:
            raise ValueError(f"quote is too short to verify (minimum {MIN_QUOTE_CHARS} characters)")

        focus: list[tuple[int, int | None, str | None]] = []
        if chunk_id:
            chunk = self.store.get_chunk(chunk_id)
            pages = self._pages_for_documents([chunk.document_id])
            focus = [(chunk.document_id, chunk.page, chunk.section)]
            if chunk.page is not None:  # quotes near a page break: also look at the next/previous page
                focus += [
                    (chunk.document_id, chunk.page - 1, None),
                    (chunk.document_id, chunk.page + 1, None),
                ]
        elif source:
            doc_ids = self.store.documents_by_source(source, collections)
            if not doc_ids:
                raise NotFoundError(f"document not found: {source}")
            pages = self._pages_for_documents(doc_ids)
            focus = self._hit_pages(quote, collections, source)
        else:
            focus = self._hit_pages(quote, collections, None)
            pages = self._pages_for_documents(doc_id for doc_id, _, _ in focus)

        def in_focus(p: PageText) -> bool:
            return any(
                p.document_id == d and p.page == pg and (sec is None or p.section == sec)
                for d, pg, sec in focus
            )

        # Strict pass over every candidate page, focus pages first.
        ordered = sorted(pages, key=lambda p: not in_focus(p))
        m = next((m for m in (match_in_page(quote, p) for p in ordered) if m), None)
        if m is None:
            m = best_match(
                quote, [p for p in ordered if in_focus(p)][:MAX_FUZZY_PAGES] or ordered[:MAX_FUZZY_PAGES]
            )
        return _to_check(quote, m, len(pages))


def _to_check(quote: str, m: Match, searched: int) -> QuoteCheck:
    verified = m.kind in ("exact", "normalized", "ellipsis")
    base = QuoteCheck(
        verified=verified,
        match=m.kind,
        similarity=1.0 if verified else m.similarity,
        quote=quote,
        pages_searched=searched,
        note=_NOTES[m.kind],
    )
    if m.page is None or (m.kind == "not_found" and m.similarity < 0.5):
        return base
    chunk = m.page.chunk_at(m.start)
    return base.model_copy(
        update={
            "source_text": m.source_text,
            "citation": citation_label(chunk.source, chunk.page, chunk.section, chunk.page_label),
            "source": chunk.source,
            "title": chunk.title,
            "page": chunk.page,
            "page_label": chunk.page_label,
            "section": chunk.section,
            "chunk_id": chunk.chunk_id,
            "collection": chunk.collection,
        }
    )
