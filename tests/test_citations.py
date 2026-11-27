"""Citation export: golden files for the three formats (no database)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from citewell.citations import FORMATS, CiteItem, cite_key, render

GOLDEN = Path(__file__).parent / "data" / "cite"

ITEMS = [
    CiteItem(
        chunk_id="a1b2c3d4e5f6a7b8c9d0",
        source="hukuk/is-kanunu_4857.pdf",
        title="İş Kanunu (4857) & Yönetmelikler",
        author="Çalışma ve Sosyal Güvenlik Bakanlığı",
        doc_date=date(2003, 6, 10),
        page=12,
        page_label="iv",
        collection="hukuk",
        quote="Yıllık ücretli izin süresi\n bir yıllık çalışma için on dört günden az olamaz.",
    ),
    CiteItem(
        chunk_id="0f9e8d7c6b5a49382716",
        source="ik/calisan-el-kitabi.pdf",
        title="Çalışan El Kitabı",
        page=4,
        page_label="4",
        collection="ik",
        quote="Konaklama için gecelik üst limit 3.500 TL'dir.",
    ),
    CiteItem(
        chunk_id="123456abcdef7890fedc",
        source="notes/{draft}_100%.md",
        section="Parola Kuralları",
        collection="default",
    ),
]


def test_golden_bibtex() -> None:
    assert render(ITEMS, "bibtex") == (GOLDEN / "export.bib").read_text(encoding="utf-8")


def test_golden_csl_json() -> None:
    assert render(ITEMS, "csl-json") == (GOLDEN / "export.json").read_text(encoding="utf-8")


def test_golden_markdown() -> None:
    assert render(ITEMS, "md") == (GOLDEN / "export.md").read_text(encoding="utf-8")
    assert render(ITEMS, "md", with_quotes=True) == (GOLDEN / "export-quotes.md").read_text(encoding="utf-8")


def test_empty_export_and_unknown_format() -> None:
    assert [render([], f) for f in FORMATS] == ["", "[]\n", ""]  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="format must be one of"):
        render(ITEMS, "ris")  # type: ignore[arg-type]


def test_keys_are_ascii_and_unique_per_passage() -> None:
    keys = [cite_key(i) for i in ITEMS]
    assert keys == ["is-kanunu-4857-piv-a1b2c3", "calisan-el-kitabi-p4-0f9e8d", "draft-100-123456"]
    assert len(set(keys)) == len(keys)
    same_page = ITEMS[1].model_copy(update={"chunk_id": "ffffffaaaa"})
    assert cite_key(same_page) != cite_key(ITEMS[1])
    assert cite_key(CiteItem(chunk_id="abcdef0000", source="....")) == "document-abcdef"
