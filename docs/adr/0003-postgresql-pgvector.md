# ADR-0003: PostgreSQL + pgvector + tsvector as the only datastore

- **Status:** Accepted
- **Date:** 2026-11-02

## Context

Hybrid retrieval needs a vector index and a full-text index. Options range from embedded stores
(Chroma, LanceDB, SQLite-vec) to dedicated engines (Qdrant, Elasticsearch/OpenSearch).

## Decision

Use one PostgreSQL database with the `pgvector` extension (HNSW, cosine) for dense retrieval and the
built-in `tsvector`/GIN full-text search with the `turkish`, `english` or `simple` configuration per
collection. Documents, chunks and metadata live in the same transactional store.

## Consequences

- One service to run (`docker compose up`), transactional re-ingest (delete + insert in one
  transaction), SQL filtering by collection and source path, familiar backup tooling.
- PostgreSQL ranks full-text matches with `ts_rank_cd` (cover density), **not BM25**. In Citewell the
  "keyword" retriever is therefore BM25-like rather than BM25; RRF only uses ranks, so this matters
  less than it would for score fusion. A true BM25 extension (e.g. `pg_search`/ParadeDB) can be added
  behind the same interface later.
- The vector column has a fixed dimension; the embedding model and dimension are recorded in
  `citewell_meta` and verified at startup (switching models requires re-ingesting).
- HNSW with filters: on pgvector ≥ 0.8 Citewell enables `hnsw.iterative_scan` so filtered queries do
  not silently return fewer rows.

## Alternatives considered

- Qdrant / Weaviate — excellent, but a second service and no SQL joins with metadata.
- Elasticsearch/OpenSearch — real BM25 and analyzers, but heavy for a local tool.
- SQLite + sqlite-vec + FTS5 — attractive for a future "single-file" mode; less mature HNSW today.
