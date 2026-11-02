from itertools import pairwise

import pytest

from citewell.chunking import chunk_page, chunk_pages
from citewell.models import Page

SENT = "Bu bir örnek cümledir ve yaklaşık elli karakter uzunluğundadır."


def _text(n: int) -> str:
    return " ".join(f"{i}. {SENT}" for i in range(n))


def test_chunks_are_verbatim_slices_and_respect_size() -> None:
    text = _text(40)
    spans = chunk_page(text, chunk_size=300, overlap=80, min_size=40)
    assert len(spans) > 1
    for start, end in spans:
        assert end - start <= 300
        chunk = text[start:end]
        assert chunk == chunk.strip()
        assert chunk.endswith(".")  # ends on a sentence boundary


def test_chunks_cover_the_whole_text() -> None:
    text = _text(30)
    spans = chunk_page(text, 250, 50, 20)
    assert spans[0][0] == 0
    assert spans[-1][1] == len(text)
    for (_, prev_end), (start, _) in pairwise(spans):
        assert start <= prev_end + 1  # no gaps (overlap or adjacent)


def test_overlap_repeats_trailing_sentences() -> None:
    text = _text(20)
    spans = chunk_page(text, 300, 120, 20)
    a, b = spans[0], spans[1]
    assert b[0] < a[1]  # overlapping


def test_zero_overlap_produces_disjoint_chunks() -> None:
    spans = chunk_page(_text(20), 300, 0, 20)
    for (_, e), (s, _) in pairwise(spans):
        assert s >= e


def test_long_sentence_is_hard_split() -> None:
    text = "kelime " * 400
    spans = chunk_page(text.strip(), 200, 0, 10)
    assert all(e - s <= 200 for s, e in spans)
    assert len(spans) >= 14


def test_tiny_tail_is_merged() -> None:
    text = "A" * 280 + ". Son."
    spans = chunk_page(text, 300, 0, 40)
    assert spans == [(0, len(text))]


def test_chunk_pages_never_crosses_pages() -> None:
    pages = [Page(number=1, text=_text(10)), Page(number=2, text=_text(10)), Page(number=3, text="")]
    drafts = chunk_pages(pages, chunk_size=200, overlap=50, min_size=20)
    assert {d.page for d in drafts} == {1, 2}
    assert [d.ord for d in drafts] == list(range(len(drafts)))
    for d in drafts:
        page_text = pages[d.page - 1].text  # type: ignore[operator]
        assert page_text[d.char_start : d.char_end] == d.text


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_empty(text: str) -> None:
    assert chunk_page(text, 100, 10, 5) == []
