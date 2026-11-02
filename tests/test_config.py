import pytest
from pydantic import ValidationError

from citewell.config import Settings
from citewell.models import Citation


def test_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CITEWELL_EMBEDDING_MODEL", "intfloat/multilingual-e5-large")
    monkeypatch.setenv("CITEWELL_DEFAULT_TOP_K", "9")
    s = Settings()
    assert s.embedding_model == "intfloat/multilingual-e5-large"
    assert s.default_top_k == 9


def test_overlap_must_be_smaller_than_chunk() -> None:
    with pytest.raises(ValidationError):
        Settings(chunk_size=100, chunk_overlap=100)


def test_citation_label() -> None:
    assert Citation(source="a.pdf", page=3, chunk_id="x", quote="q").label() == "a.pdf, s. 3"
    assert Citation(source="b.md", section="Giriş", chunk_id="x", quote="q").label() == "b.md, Giriş"
    assert Citation(source="c.txt", chunk_id="x", quote="q").label() == "c.txt"
