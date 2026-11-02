from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from citewell.config import Settings

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "examples" / "corpus"
CORPUS_EN = ROOT / "examples" / "corpus-en"
EVAL_TR = ROOT / "examples" / "eval" / "tr-sample.jsonl"

TEST_DB_URL = os.environ.get("CITEWELL_TEST_DATABASE_URL")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if TEST_DB_URL:
        return
    skip = pytest.mark.skip(reason="set CITEWELL_TEST_DATABASE_URL to run database tests")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


def make_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "database_url": TEST_DB_URL or "postgresql://invalid",
        "embedding_backend": "hash",
        "embedding_dim": 256,
        "reranker_backend": "lexical",
        "chunk_size": 600,
        "chunk_overlap": 100,
        "pool_max_size": 4,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def settings() -> Settings:
    return make_settings()


@pytest.fixture(scope="session")
def citewell(settings: Settings) -> Iterator[object]:
    """A Citewell instance on a freshly reset test database with the sample corpus ingested."""
    import psycopg

    from citewell.app import Citewell

    assert TEST_DB_URL
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE")
        conn.execute("CREATE SCHEMA public")
    cw = Citewell(settings)
    cw.init_db()
    cw.ingest.ingest_paths([CORPUS])
    cw.ingest.ingest_paths([CORPUS_EN], collection="handbook-en", language="english")
    yield cw
    cw.close()
