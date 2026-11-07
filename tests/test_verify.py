import pytest

from citewell.models import ChunkRecord
from citewell.verify import best_match, match_in_page, normalize, rebuild_pages

PAGE = (
    "Madde 15 - Taraflarca iş sözleşmesine bir deneme kaydı konulduğunda, bunun süresi en çok iki ay "
    "olabilir. Ancak deneme süresi toplu iş sözleşmeleriyle dört aya kadar uzatılabilir.\n"
    "İşçilerin gece çalışmaları yedibuçuk saati geçemez."
)


def _chunk(
    cid: str, start: int, end: int, text: str = PAGE, page: int | None = 10, ord_: int = 0
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=cid,
        collection="mevzuat",
        document_id=1,
        source="is-kanunu.pdf",
        title="İş Kanunu",
        ord=ord_,
        page=page,
        section=None,
        char_start=start,
        char_end=end,
        text=text[start:end],
    )


def _page():  # type: ignore[no-untyped-def]
    # two overlapping chunks covering the page
    return rebuild_pages([_chunk("b", 90, len(PAGE), ord_=1), _chunk("a", 0, 120)])[0]


def test_rebuild_pages_merges_overlapping_chunks() -> None:
    page = _page()
    assert page.text == PAGE
    assert [c.chunk_id for c in page.chunks] == ["a", "b"]
    assert page.chunk_at(5).chunk_id == "a"
    assert page.chunk_at(len(PAGE) - 3).chunk_id == "b"


def test_normalize_keeps_offset_map() -> None:
    n = normalize("  İSTANBUL’da   “ISPARTA” —  ­test ")
    assert n.text == 'istanbul\'da "ısparta" - test'
    assert n.index[0] == 2  # first non-space character


def test_exact_match_ignores_whitespace() -> None:
    m = match_in_page("bunun süresi en çok\n  iki ay olabilir.", _page())
    assert m is not None
    assert m.kind == "exact"
    assert m.source_text == "bunun süresi en çok iki ay olabilir."


def test_normalized_match_case_and_typography() -> None:
    m = match_in_page("İŞÇİLERİN GECE ÇALIŞMALARI yedibuçuk saati geçemez", _page())
    assert m is not None
    assert m.kind == "normalized"
    assert m.source_text == "İşçilerin gece çalışmaları yedibuçuk saati geçemez"
    m = match_in_page("Madde 15 – Taraflarca", _page())  # en dash vs hyphen
    assert m is not None
    assert m.kind == "normalized"


def test_ellipsis_parts_in_order() -> None:
    m = match_in_page("bunun süresi en çok iki ay olabilir … dört aya kadar uzatılabilir", _page())
    assert m is not None
    assert m.kind == "ellipsis"
    assert m.source_text is not None
    assert m.source_text.startswith("bunun süresi") and m.source_text.endswith("uzatılabilir")
    assert (
        match_in_page("dört aya kadar uzatılabilir ... bunun süresi en çok", _page()) is None
    )  # wrong order


def test_fuzzy_returns_closest_wording() -> None:
    m = best_match("deneme süresi toplu sözleşmelerle en fazla dört aya kadar uzatılabilir", [_page()])
    assert m.kind == "fuzzy"
    assert 0.82 <= m.similarity < 1
    assert m.source_text is not None
    assert "dört aya kadar uzatılabilir" in m.source_text


def test_not_found() -> None:
    m = best_match("Yıllık izin süresi otuz gündür ve bölünemez.", [_page()])
    assert m.kind == "not_found"
    assert m.similarity < 0.82


@pytest.mark.parametrize("quote", ["", "   "])
def test_empty_quote_never_matches(quote: str) -> None:
    assert match_in_page(quote, _page()) is None
