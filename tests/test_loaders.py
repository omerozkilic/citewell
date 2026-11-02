from pathlib import Path

import pytest

from citewell.loaders import (
    UnsupportedFormatError,
    detect_mime,
    iter_files,
    load_bytes,
    load_file,
    load_html,
    load_markdown,
    load_text,
)

from .conftest import CORPUS


def test_markdown_sections_keep_heading_path() -> None:
    md = "---\ntitle: x\n---\n# Kılavuz\nGiriş.\n## Bölüm A\nMetin A.\n### Alt\nMetin alt.\n## Bölüm B\n```\n# kod\n```\nB."
    pages, meta = load_markdown(md)
    assert meta["title"] == "Kılavuz"
    assert [p.section for p in pages] == [
        "Kılavuz",
        "Kılavuz > Bölüm A",
        "Kılavuz > Bölüm A > Alt",
        "Kılavuz > Bölüm B",
    ]
    assert "# kod" in pages[-1].text  # headings inside code fences are not sections
    assert all(p.number is None for p in pages)


def test_text_form_feed_marks_pages() -> None:
    pages, _ = load_text("bir\fiki\f\füç")
    assert [(p.number, p.text) for p in pages] == [(1, "bir"), (2, "iki"), (4, "üç")]


def test_text_without_pages() -> None:
    pages, _ = load_text("tek sayfa")
    assert pages[0].number is None


def test_html_strips_scripts_and_reads_title() -> None:
    html = "<html><head><title>Başlık</title><style>p{}</style></head><body><h1>Üst</h1><p>Para&nbsp;graf</p><script>x()</script></body></html>"
    pages, meta = load_html(html)
    assert meta["title"] == "Başlık"
    assert "x()" not in pages[0].text
    assert "Üst" in pages[0].text and "Para graf" in pages[0].text


def test_pdf_pages_are_numbered() -> None:
    doc = load_file(CORPUS / "calisan-el-kitabi.pdf")
    assert doc.mime == "application/pdf"
    assert doc.title == "Defne Yazılım Çalışan El Kitabı"
    assert [p.number for p in doc.pages] == [1, 2, 3, 4, 5, 6]
    assert "14 iş günü" in doc.pages[1].text
    assert "harcırahı" in doc.pages[3].text


def test_load_bytes_decodes_cp1254() -> None:
    doc = load_bytes("Çalışan ğüşıöç".encode("cp1254"), "eski.txt")
    assert doc.pages[0].text == "Çalışan ğüşıöç"
    assert doc.title == "eski"


def test_sha_changes_with_content() -> None:
    assert load_bytes(b"a", "x.txt").sha256 != load_bytes(b"b", "x.txt").sha256


def test_unsupported() -> None:
    with pytest.raises(UnsupportedFormatError):
        detect_mime("a.xlsx")


def test_iter_files_relative_sources_and_hidden(tmp_path: Path) -> None:
    (tmp_path / "alt").mkdir()
    (tmp_path / "alt" / "b.md").write_text("# b")
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "c.bin").write_bytes(b"\0")
    (tmp_path / ".gizli").mkdir()
    (tmp_path / ".gizli" / "d.md").write_text("d")
    found = [src for _, src in iter_files([tmp_path])]
    assert found == ["a.txt", "alt/b.md"]
    assert [src for _, src in iter_files([tmp_path], recursive=False)] == ["a.txt"]
    assert [src for _, src in iter_files([tmp_path / "a.txt"])] == ["a.txt"]
    with pytest.raises(FileNotFoundError):
        list(iter_files([tmp_path / "yok"]))
