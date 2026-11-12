"""Page-aware, sentence-respecting chunker.

Design goals (see ADR-0006):

* a chunk never crosses a page boundary, so every chunk has exactly one page;
* chunk text is a verbatim slice of the page text (``page.text[start:end]``),
  so offsets and quotes are always exact;
* chunks prefer to end on sentence/paragraph boundaries and overlap by whole
  sentences.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from citewell.models import ChunkDraft, Page

_BOUNDARY_RE = re.compile(r"(?<=[.!?…:;])\s+|\n\s*\n|\n(?=\s*(?:[-*•]|\d+[.)])\s)|\n(?=\|)")


@dataclass(frozen=True, slots=True)
class _Span:
    start: int
    end: int


def _strip(text: str, sp: _Span) -> _Span:
    start, end = sp.start, sp.end
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return _Span(start, end)


def _units(text: str, max_len: int) -> list[_Span]:
    """Sentence-ish spans covering ``text`` (whitespace between spans dropped)."""
    spans: list[_Span] = []
    pos = 0
    for m in _BOUNDARY_RE.finditer(text):
        if m.start() > pos:
            spans.append(_Span(pos, m.start()))
        pos = m.end()
    if pos < len(text):
        spans.append(_Span(pos, len(text)))
    spans = [s for s in (_strip(text, sp) for sp in spans) if s.end > s.start]

    # Hard-split spans that are longer than a chunk, on whitespace when possible.
    out: list[_Span] = []
    for sp in spans:
        start = sp.start
        while sp.end - start > max_len:
            cut = text.rfind(" ", start, start + max_len)
            if cut <= start + max_len // 2:
                cut = start + max_len
            out.append(_Span(start, cut))
            start = cut
            while start < sp.end and text[start].isspace():
                start += 1
        if sp.end > start:
            out.append(_Span(start, sp.end))
    return out


def chunk_page(text: str, chunk_size: int, overlap: int, min_size: int) -> list[tuple[int, int]]:
    """Return ``(start, end)`` offsets of chunks within ``text``."""
    units = _units(text, chunk_size)
    if not units:
        return []
    chunks: list[tuple[int, int]] = []
    i = 0
    while i < len(units):
        start = units[i].start
        j = i
        while j + 1 < len(units) and units[j + 1].end - start <= chunk_size:
            j += 1
        end = units[j].end
        chunks.append((start, end))
        if j + 1 >= len(units):
            break
        # Next chunk starts at the earliest unit that keeps <= `overlap` chars of context.
        nxt = j + 1
        while nxt - 1 > i and end - units[nxt - 1].start <= overlap:
            nxt -= 1
        i = nxt

    # Merge a tiny tail into its predecessor when it stays reasonably sized.
    if len(chunks) > 1:
        tail_start, tail_end = chunks[-1]
        prev_start, _ = chunks[-2]
        if tail_end - tail_start < min_size and tail_end - prev_start <= int(chunk_size * 1.25):
            chunks[-2:] = [(prev_start, tail_end)]
    return chunks


def chunk_pages(
    pages: Iterable[Page], chunk_size: int = 1000, overlap: int = 150, min_size: int = 40
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    for page in pages:
        for start, end in chunk_page(page.text, chunk_size, overlap, min_size):
            body = page.text[start:end]
            if not body.strip():
                continue
            drafts.append(
                ChunkDraft(
                    ord=len(drafts),
                    page=page.number,
                    page_label=page.label,
                    section=page.section,
                    char_start=start,
                    char_end=end,
                    text=body,
                )
            )
    return drafts
