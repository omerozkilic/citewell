import importlib.util
import json
from pathlib import Path
from types import ModuleType

from citewell.models import Page

from .conftest import ROOT


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_mevzuat_eval", ROOT / "scripts" / "build_mevzuat_eval.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_article_spans() -> None:
    m = _script()
    pages = [
        Page(number=1, text="İŞ KANUNU\nAmaç Madde 1 - Bu Kanunun amacı …\nTanımlar Madde 2 - İşçi …"),
        Page(number=2, text="… devam eden tanımlar. bu Kanunun 17 nci maddesi uyarınca"),
        Page(number=3, text="Madde 3 - Üçüncü madde en üstte başlar. Geçici Madde 1 - geçici hüküm"),
        Page(number=4, text="Uzun bir giriş paragrafı " * 10 + "MADDE 4 – Dördüncü madde"),
    ]
    starts = m.article_starts(pages)
    assert sorted(starts) == [1, 2, 3, 4]  # cross-references and Geçici Madde ignored
    assert m.article_pages(starts, 1) == [1]
    assert m.article_pages(starts, 2) == [1, 2]  # continues on page 2, ends before page 3's top heading
    assert m.article_pages(starts, 3) == [3, 4]  # Madde 4 starts mid-page 4
    assert m.article_pages(starts, 4) == [4]
    assert m.article_pages(starts, 99) == []


def test_main_builds_dataset(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from reportlab.pdfgen import canvas

    m = _script()
    pdf_dir = tmp_path / "pdf"
    pdf_dir.mkdir()
    c = canvas.Canvas(str(pdf_dir / "1.5.4857.pdf"))
    c.drawString(72, 750, "Deneme sureli is sozlesmesi Madde 15 - Deneme suresi en cok iki ay olabilir.")
    c.showPage()
    c.drawString(72, 750, "Madde 16 - Baska bir hukum.")
    c.showPage()
    c.save()
    c = canvas.Canvas(str(pdf_dir / "KARARNAMELER 30-09-2021.pdf"))  # a date, not a law number
    c.drawString(72, 750, "Madde 1 - Baska bir metin.")
    c.showPage()
    c.save()
    questions = tmp_path / "q.jsonl"
    questions.write_text(
        "// comment\n"
        + json.dumps({"id": "a", "law": "4857", "article": 15, "query": "Deneme süresi?"})
        + "\n"
        + json.dumps({"id": "b", "law": "6698", "article": 3, "query": "Açık rıza?"})
        + "\n"
        + json.dumps({"id": "c", "law": "4857", "article": 99, "query": "Yok"})
        + "\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.jsonl"
    assert m.main([str(pdf_dir), "-q", str(questions), "-o", str(out)]) == 0
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows == [
        {
            "id": "a",
            "query": "Deneme süresi?",
            "relevant": [{"source": "1.5.4857.pdf", "pages": [1]}],
            "collection": "mevzuat",
            "tags": ["law:4857", "madde:15"],
        }
    ]


def test_bundled_questions_are_valid() -> None:
    lines = [
        ln
        for ln in (ROOT / "examples/eval/mevzuat-questions.jsonl").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("//")
    ]
    ids = set()
    for ln in lines:
        q = json.loads(ln)
        assert {"id", "law", "article", "query"} <= set(q)
        assert q["id"] not in ids
        ids.add(q["id"])
    assert len(lines) >= 30
