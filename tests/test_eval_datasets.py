"""The bundled eval datasets: well formed, and every label backed by the sample corpus."""

from __future__ import annotations

import re
from collections import Counter
from functools import cache

import pytest

from citewell.evaluation import EvalQuery, load_dataset
from citewell.loaders import load_file
from citewell.text import tr_lower

from .conftest import ROOT

CORPUS = ROOT / "examples" / "corpus"
EVAL = ROOT / "examples" / "eval"
SAMPLE_SETS = ["tr-sample.jsonl", "tr-sample-ascii.jsonl", "tr-extended.jsonl"]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", tr_lower(text)).strip()


@cache
def _pages(source: str) -> dict[int | None, str]:
    """Normalised text of a corpus document: per page for PDFs, one entry (``None``) otherwise."""
    doc = load_file(CORPUS / source)
    if all(p.number is None for p in doc.pages):
        return {None: _norm(" ".join(p.text for p in doc.pages))}
    return {p.number: _norm(p.text) for p in doc.pages}


def _text_of(query: EvalQuery) -> str:
    parts: list[str] = []
    for item in query.relevant:
        pages = _pages(item.source)
        wanted = item.page_set()
        parts += [t for number, t in pages.items() if wanted is None or number in wanted]
    return " ".join(parts)


@pytest.mark.parametrize("name", SAMPLE_SETS)
def test_sample_sets_point_at_real_documents_and_pages(name: str) -> None:
    queries = load_dataset(EVAL / name)
    ids = [q.id for q in queries]
    assert len(ids) == len(set(ids)), "duplicate ids"
    for q in queries:
        assert q.query.strip(), q.id
        for item in q.relevant:
            pages = _pages(item.source)
            wanted = item.page_set()
            assert wanted is None or wanted <= set(pages), f"{q.id}: page missing in {item.source}"


def test_extended_set_labels_are_backed_by_the_corpus() -> None:
    queries = load_dataset(EVAL / "tr-extended.jsonl")
    for q in queries:
        assert q.answers, f"{q.id} has no answers"
        text = _text_of(q)
        for answer in q.answers:
            assert _norm(answer) in text, f"{q.id}: {answer!r} not found in its relevant passages"


def test_extended_set_covers_the_hard_kinds() -> None:
    queries = load_dataset(EVAL / "tr-extended.jsonl")
    tags = Counter(t for q in queries for t in q.tags)
    assert len(queries) >= 40
    for kind in ("no-shared-words", "typo", "numbers", "dates", "yes-no", "multi-source", "two-pages"):
        assert tags[kind] >= 1, kind
    # Several questions need more than one place: those list every place that is needed.
    assert any(len(q.relevant) > 1 for q in queries)


def test_extended_questions_are_new() -> None:
    old = {_norm(q.query) for q in load_dataset(EVAL / "tr-sample.jsonl")}
    new = [_norm(q.query) for q in load_dataset(EVAL / "tr-extended.jsonl")]
    assert not old & set(new), "a question already exists in tr-sample.jsonl"
    assert len(new) == len(set(new))
