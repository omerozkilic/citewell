"""PostgreSQL repository: collections, documents, chunks and the two retrievers."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import numpy as np
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from citewell import db
from citewell.embeddings import Vector
from citewell.models import ChunkDraft, ChunkRecord, Collection, DocumentInfo, LoadedDocument
from citewell.text import tr_lower

COLLECTION_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class NotFoundError(LookupError):
    pass


def chunk_id(collection: str, source: str, sha256: str, ord_: int) -> str:
    """Stable, content-addressed chunk id: re-ingesting identical bytes yields identical ids."""
    raw = f"{collection}\x00{source}\x00{sha256}\x00{ord_}".encode()
    return hashlib.sha1(raw, usedforsecurity=False).hexdigest()[:20]


def _tsquery_literal(lexemes: Sequence[str]) -> str:
    def esc(lex: str) -> str:
        return "'" + lex.replace("\\", "\\\\").replace("'", "''") + "'"

    return " | ".join(esc(lx) for lx in lexemes)


@dataclass(slots=True)
class RetrievedId:
    chunk_id: str
    score: float


_CHUNK_SELECT = """
    SELECT c.id AS chunk_id, col.name AS collection, c.document_id, d.source, d.title,
           c.ord, c.page, c.section, c.char_start, c.char_end, c.text
    FROM chunks c
    JOIN documents d ON d.id = c.document_id
    JOIN collections col ON col.id = c.collection_id
"""


class Store:
    def __init__(self, pool: ConnectionPool):
        self.pool = pool
        self._pgvector_version: tuple[int, ...] | None = None

    @contextmanager
    def conn(self) -> Iterator[psycopg.Connection]:
        with self.pool.connection() as conn:
            yield conn

    # ------------------------------------------------------------------ schema

    def migrate(self, embedding_dim: int, embedding_model: str) -> list[str]:
        with self.conn() as conn:
            return db.migrate(conn, embedding_dim, embedding_model)

    def meta(self) -> dict[str, str] | None:
        with self.conn() as conn:
            return db.read_meta(conn)

    def pgvector_version(self) -> tuple[int, ...] | None:
        if self._pgvector_version is None:
            with self.conn() as conn:
                self._pgvector_version = db.pgvector_version(conn)
        return self._pgvector_version

    # ------------------------------------------------------------- collections

    def ensure_collection(
        self, name: str, language: str = "turkish", description: str | None = None
    ) -> Collection:
        if not COLLECTION_NAME_RE.match(name):
            raise ValueError("collection names must be lowercase letters, digits, '-' or '_' (max 64 chars)")
        with self.conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                INSERT INTO collections (name, language, description) VALUES (%s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET description = COALESCE(EXCLUDED.description,
                                                                        collections.description)
                RETURNING id, name, language, description, created_at
                """,
                (name, language, description),
            )
            row = cur.fetchone()
            conn.commit()
        assert row is not None
        return Collection(**row)

    def get_collection(self, name: str) -> Collection:
        for c in self.list_collections():
            if c.name == name:
                return c
        raise NotFoundError(f"collection not found: {name}")

    def list_collections(self) -> list[Collection]:
        with self.conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                SELECT col.id, col.name, col.language, col.description, col.created_at,
                       (SELECT count(*) FROM documents d WHERE d.collection_id = col.id) AS document_count,
                       (SELECT count(*) FROM chunks c WHERE c.collection_id = col.id) AS chunk_count
                FROM collections col ORDER BY col.name
                """
            )
            return [Collection(**r) for r in cur.fetchall()]

    def delete_collection(self, name: str) -> bool:
        with self.conn() as conn:
            cur = conn.execute("DELETE FROM collections WHERE name = %s", (name,))
            conn.commit()
            return cur.rowcount > 0

    # --------------------------------------------------------------- documents

    def document_sha(self, collection_id: int, source: str) -> str | None:
        with self.conn() as conn:
            row = conn.execute(
                "SELECT sha256 FROM documents WHERE collection_id = %s AND source = %s",
                (collection_id, source),
            ).fetchone()
        return str(row[0]) if row else None

    def replace_document(
        self,
        collection: Collection,
        doc: LoadedDocument,
        chunks: Sequence[ChunkDraft],
        embeddings: Vector,
    ) -> int:
        """Atomically replace a document and all of its chunks."""
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings length mismatch")
        page_numbers = [p.number for p in doc.pages if p.number is not None]
        with self.conn() as conn, conn.transaction():
            conn.execute(
                "DELETE FROM documents WHERE collection_id = %s AND source = %s",
                (collection.id, doc.source),
            )
            row = conn.execute(
                """
                INSERT INTO documents (collection_id, source, title, mime, sha256, page_count, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (
                    collection.id,
                    doc.source,
                    doc.title,
                    doc.mime,
                    doc.sha256,
                    doc.metadata.get("total_pages") or (max(page_numbers) if page_numbers else None),
                    Jsonb(doc.metadata),
                ),
            ).fetchone()
            assert row is not None
            doc_id = int(row[0])
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO chunks (id, document_id, collection_id, ord, page, section,
                                        char_start, char_end, text, tsv, embedding)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, to_tsvector(%s::regconfig, %s), %s)
                    """,
                    [
                        (
                            chunk_id(collection.name, doc.source, doc.sha256, ch.ord),
                            doc_id,
                            collection.id,
                            ch.ord,
                            ch.page,
                            ch.section,
                            ch.char_start,
                            ch.char_end,
                            ch.text,
                            collection.language,
                            tr_lower(" ".join(filter(None, [ch.section, ch.text])), collection.language),
                            np.asarray(emb, dtype=np.float32),
                        )
                        for ch, emb in zip(chunks, embeddings, strict=True)
                    ],
                )
        return doc_id

    def list_documents(self, collection: str | None = None) -> list[DocumentInfo]:
        sql = """
            SELECT d.id, col.name AS collection, d.source, d.title, d.mime, d.sha256, d.page_count,
                   (d.metadata->>'pages_without_text')::int AS pages_without_text,
                   d.ingested_at, (SELECT count(*) FROM chunks c WHERE c.document_id = d.id) AS chunk_count
            FROM documents d JOIN collections col ON col.id = d.collection_id
        """
        params: tuple[Any, ...] = ()
        if collection:
            sql += " WHERE col.name = %s"
            params = (collection,)
        sql += " ORDER BY col.name, d.source"
        with self.conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            return [DocumentInfo(**r) for r in cur.fetchall()]

    def delete_document(self, collection: str, source: str) -> bool:
        with self.conn() as conn:
            cur = conn.execute(
                """
                DELETE FROM documents d USING collections col
                WHERE d.collection_id = col.id AND col.name = %s AND d.source = %s
                """,
                (collection, source),
            )
            conn.commit()
            return cur.rowcount > 0

    # ------------------------------------------------------------------ chunks

    def get_chunks(self, ids: Sequence[str]) -> dict[str, ChunkRecord]:
        if not ids:
            return {}
        with self.conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_CHUNK_SELECT + " WHERE c.id = ANY(%s)", (list(ids),))
            return {r["chunk_id"]: ChunkRecord(**r) for r in cur.fetchall()}

    def get_chunk(self, chunk_id_: str) -> ChunkRecord:
        found = self.get_chunks([chunk_id_])
        if chunk_id_ not in found:
            raise NotFoundError(f"chunk not found: {chunk_id_}")
        return found[chunk_id_]

    def neighbours(self, chunk_id_: str, window: int = 1) -> list[ChunkRecord]:
        """The chunk plus ``window`` chunks before/after it in the same document."""
        with self.conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                _CHUNK_SELECT
                + """
                WHERE c.document_id = (SELECT document_id FROM chunks WHERE id = %(id)s)
                  AND c.ord BETWEEN (SELECT ord FROM chunks WHERE id = %(id)s) - %(w)s
                                AND (SELECT ord FROM chunks WHERE id = %(id)s) + %(w)s
                ORDER BY c.ord
                """,
                {"id": chunk_id_, "w": window},
            )
            rows = [ChunkRecord(**r) for r in cur.fetchall()]
        if not rows:
            raise NotFoundError(f"chunk not found: {chunk_id_}")
        return rows

    # -------------------------------------------------------------- retrievers

    def vector_search(
        self,
        query_vec: Vector,
        collection_ids: Sequence[int],
        limit: int,
        source_prefix: str | None = None,
    ) -> list[RetrievedId]:
        """Cosine similarity over the HNSW index. Score is ``1 - cosine distance``."""
        where = ["c.collection_id = ANY(%(cols)s)"]
        params: dict[str, Any] = {
            "q": np.asarray(query_vec, dtype=np.float32),
            "cols": list(collection_ids),
            "lim": limit,
        }
        if source_prefix:
            where.append("d.source LIKE %(src)s")
            params["src"] = _like_prefix(source_prefix)
        sql = f"""
            SELECT c.id, 1 - (c.embedding <=> %(q)s) AS score
            FROM chunks c JOIN documents d ON d.id = c.document_id
            WHERE {" AND ".join(where)}
            ORDER BY c.embedding <=> %(q)s
            LIMIT %(lim)s
        """
        with self.conn() as conn, conn.transaction():
            conn.execute(f"SET LOCAL hnsw.ef_search = {max(40, min(1000, limit * 2))}")
            version = self.pgvector_version() or ()
            if version >= (0, 8):
                # Keep scanning the graph when filters discard candidates.
                conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
            rows = conn.execute(sql, params).fetchall()
        # relaxed_order may return slightly out-of-order rows; re-sort exactly.
        hits = [RetrievedId(str(r[0]), float(r[1])) for r in rows]
        hits.sort(key=lambda h: -h.score)
        return hits

    def query_lexemes(self, query: str, language: str) -> list[str]:
        with self.conn() as conn:
            rows = conn.execute(
                "SELECT lexeme FROM unnest(to_tsvector(%s::regconfig, %s))",
                (language, tr_lower(query, language)),
            ).fetchall()
        return [str(r[0]) for r in rows]

    def keyword_search(
        self,
        query: str,
        language: str,
        collection_ids: Sequence[int],
        limit: int,
        source_prefix: str | None = None,
    ) -> list[RetrievedId]:
        """Full-text search with OR semantics over stemmed lexemes, ranked by ``ts_rank_cd``.

        Natural-language questions rarely contain *all* terms of the answer, so the
        query is turned into ``lex1 | lex2 | …`` instead of ``websearch_to_tsquery``'s AND.
        """
        lexemes = self.query_lexemes(query, language)
        if not lexemes:
            return []
        where = ["c.collection_id = ANY(%(cols)s)", "c.tsv @@ q.query"]
        params: dict[str, Any] = {
            "tsq": _tsquery_literal(lexemes),
            "cols": list(collection_ids),
            "lim": limit,
        }
        if source_prefix:
            where.append("d.source LIKE %(src)s")
            params["src"] = _like_prefix(source_prefix)
        sql = f"""
            WITH q AS (SELECT %(tsq)s::tsquery AS query)
            SELECT c.id, ts_rank_cd(c.tsv, q.query, 1) AS score
            FROM chunks c JOIN documents d ON d.id = c.document_id, q
            WHERE {" AND ".join(where)}
            ORDER BY score DESC, c.id
            LIMIT %(lim)s
        """
        with self.conn() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [RetrievedId(str(r[0]), float(r[1])) for r in rows]


def _like_prefix(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
