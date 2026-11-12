# Architecture

```mermaid
flowchart LR
  subgraph Clients
    CD[Claude Desktop] -->|stdio| MCP
    CC[Claude Code / Cursor] -->|Streamable HTTP /mcp| MCP
    U[Scripts, UIs] -->|REST /v1| API
    T[Terminal] --> CLI
  end
  MCP[MCP server<br/>read-only] --> S[SearchService]
  API[FastAPI] --> S
  API --> I[IngestService]
  CLI[Typer CLI] --> S
  CLI --> I
  CLI --> EV[Eval harness]
  EV --> S
  I --> LD[Loaders] --> CH[Chunker] --> EM[Embedder]
  EM --> ST[(Store<br/>PostgreSQL)]
  S --> EM
  S --> ST
  S --> RR[Reranker]
```

## Modules

| Module | Responsibility |
|---|---|
| `loaders` | File → `Page`s. PDF via pypdf (with line reflow), Markdown sections by heading path, text with form-feed pages, HTML, DOCX, and (in `extra_loaders`, standard library only) PPTX slides, XLSX sheets, CSV, EPUB chapters and EML messages. NFC normalisation, hyphenation repair, cp1254 fallback. |
| `chunking` | Sentence-ish units packed up to `chunk_size`, whole-sentence overlap, never across pages, offsets into the page text. |
| `embeddings` | `SentenceTransformerEmbedder` (bge-m3, e5 with prefixes) and `HashEmbedder` (tests). |
| `ingest` | Hash-based idempotency, contextual headers (title — section) for embedding, atomic replace. |
| `store` | SQL for collections, documents, chunks; `vector_search` (HNSW, cosine) and `keyword_search` (tsvector, OR query, `ts_rank_cd`). |
| `fusion` | Reciprocal Rank Fusion. |
| `search` | Mode selection, per-language keyword rankings, RRF, optional rerank, quote selection. |
| `mcp_server` / `api` / `cli` | Interfaces. |
| `evaluation` | Metrics and reports. |

## Data model

```mermaid
erDiagram
  collections ||--o{ documents : contains
  documents ||--o{ chunks : "split into"
  collections {
    bigint id
    text name
    text language "turkish | english | simple"
  }
  documents {
    bigint id
    text source "path relative to ingest root"
    text sha256
    int page_count
    jsonb metadata
  }
  chunks {
    text id "sha1(collection, source, sha256, ord)[:20]"
    int ord
    int page
    text section
    int char_start
    int char_end
    text text
    tsvector tsv "to_tsvector(language, tr_lower(section + text))"
    vector embedding "vector(dim), HNSW cosine"
  }
```

## Query pipeline

1. Resolve collections (default, explicit list, or `*`).
2. **Vector**: embed the query (e5: `query: ` prefix), `ORDER BY embedding <=> q LIMIT 40` with
   `hnsw.ef_search` raised and, on pgvector ≥ 0.8, `hnsw.iterative_scan = relaxed_order` so collection /
   source filters do not starve results.
3. **Keyword**: `to_tsvector(language, tr_lower(query))` → lexemes → `'a' | 'b' | 'c'` tsquery,
   ranked with `ts_rank_cd(…, 1)`; one ranking per language.
4. **Fuse** with RRF (k = 60). Per-retriever scores and ranks are kept in `hit.scores` for debugging.
5. **Rerank** (optional) the top 30 with the cross-encoder.
6. Fetch chunk records and pick the **best quote**: the sentence window of the chunk with the
   highest overlap of query stems, max 320 characters, verbatim.

## Design decisions

See the [ADRs](adr/index.md).
