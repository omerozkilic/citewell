<div align="center">

# Citewell

**Citation-grounded document memory for AI assistants.**<br>
Offline · MCP-native · Turkish-ready

[![CI](https://github.com/omerozkilic/citewell/actions/workflows/ci.yml/badge.svg)](https://github.com/omerozkilic/citewell/actions/workflows/ci.yml)
[![CodeQL](https://github.com/omerozkilic/citewell/actions/workflows/codeql.yml/badge.svg)](https://github.com/omerozkilic/citewell/actions/workflows/codeql.yml)
[![codecov](https://codecov.io/gh/omerozkilic/citewell/branch/main/graph/badge.svg)](https://codecov.io/gh/omerozkilic/citewell)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-mkdocs-blueviolet)](https://omerozkilic.github.io/citewell)

[Türkçe README](README.tr.md) · [Documentation](https://omerozkilic.github.io/citewell) · [Architecture decisions](docs/adr/index.md)

</div>

---

Citewell is a **headless RAG server** that gives Claude Desktop, Claude Code, Cursor and any other
[MCP](https://modelcontextprotocol.io) client access to *your* documents — and every passage it
returns comes with **file, page, chunk id and a verbatim quote**, so answers can be checked.

It has **no LLM of its own and needs no API key**. It retrieves; your assistant writes the answer.

```text
You ▸ Ankara'da otelde bir gece için en fazla ne kadar harcayabilirim?

Claude ▸ (calls citewell.search_documents)
         Ankara, İstanbul ve İzmir'de gecelik konaklama üst sınırı 3.500 TL'dir [1].

         Kaynaklar
         [1] calisan-el-kitabi.pdf, s. 4 — "İş seyahatlerinde konaklama için gecelik üst sınır
             İstanbul, Ankara ve İzmir'de 3.500 TL, diğer şehirlerde 2.500 TL'dir."
```

## Why Citewell?

- **Cited, verifiable passages** — page-aware chunking that never crosses page boundaries, verbatim
  quotes, stable chunk ids ([ADR-0006](docs/adr/0006-page-aware-chunking.md)), and a `verify_quote`
  tool so assistants can check a quotation against the source before presenting it. Printed page
  numbers from the PDF are shown when they differ from the physical page (`s. 12 (PDF s. 17)`).
- **MCP-native** — stdio for desktop clients, Streamable HTTP at `/mcp`, structured tool output,
  resources and a citation prompt. Read-only by design ([ADR-0007](docs/adr/0007-read-only-mcp.md)).
- **Hybrid search** — pgvector (HNSW) + PostgreSQL full-text search fused with Reciprocal Rank Fusion,
  optional `bge-reranker-v2-m3` cross-encoder ([ADR-0004](docs/adr/0004-hybrid-search-rrf.md)).
- **Turkish first** — Turkish stemming (`tsvector` `turkish` config), correct `I/ı` – `İ/i` casing,
  search that works without Turkish characters (`ogrenci izni` finds `öğrenci izni`), cp1254
  decoding, multilingual `bge-m3` embeddings, Turkish eval sets.
- **Offline & private** — local models; after a one-time download nothing leaves your machine.
- **Measured** — built-in eval: Recall@k, MRR, hit rate, page hit rate, p50/p95 latency.
- **One command** — `docker compose up`. PostgreSQL is the only dependency.

## Quickstart (PyPI, no clone)

```bash
uv tool install "citewell[models]"      # or: pipx install "citewell[models]"

# PostgreSQL + pgvector (any PostgreSQL 15+ with pgvector works)
docker run -d --name citewell-db -p 127.0.0.1:5432:5432 \
  -e POSTGRES_USER=citewell -e POSTGRES_PASSWORD=citewell -e POSTGRES_DB=citewell \
  -v citewell-pgdata:/var/lib/postgresql/data pgvector/pgvector:pg17

citewell init
citewell models download                # once (~4–5 GB), needs internet; offline afterwards
citewell ingest ~/Documents/policies -c policies
citewell search "yıllık izin kaç gün?" -c policies
```

Then [connect your assistant](#connect-your-assistant) — e.g. Claude Code:
`claude mcp add -s user citewell -- citewell mcp`

## Quickstart (Docker)

```bash
git clone https://github.com/omerozkilic/citewell && cd citewell
docker compose up -d                                   # PostgreSQL + Citewell on localhost:8000

cp -r ~/Documents/handbooks/* data/                    # PDF, Markdown, TXT, HTML, DOCX
docker compose run --rm citewell models download       # once (~2–3 GB), needs internet
docker compose run --rm citewell ingest /data
docker compose run --rm citewell search "yıllık izin kaç gün?"
```

- REST API & OpenAPI docs: <http://localhost:8000/docs>
- MCP endpoint (Streamable HTTP): <http://localhost:8000/mcp>

No documents at hand? Use the bundled sample corpus (a fictional Turkish company handbook):

```bash
docker compose run --rm -v ./examples:/examples:ro citewell ingest /examples/corpus
docker compose run --rm citewell search "Ankara'da otelde bir gece için en fazla ne kadar harcayabilirim?"
```

> A database is tied to the embedding model it was initialised with (`citewell doctor` shows it).
> To switch models, use a fresh database volume and re-ingest.

## Quickstart (local, uv)

```bash
uv sync --extra models
docker compose up -d db
uv run citewell init
uv run citewell ingest ./my-docs --collection handbook
uv run citewell search "parola en az kaç karakter olmalı?" -c handbook
```

## Connect your assistant

<details open>
<summary><b>Claude Code</b></summary>

```bash
# stdio, installed from PyPI (`uv tool install "citewell[models]"`)
claude mcp add -s user citewell -- citewell mcp

# HTTP (server running via docker compose or `citewell serve`)
claude mcp add -s user --transport http citewell http://localhost:8000/mcp

# stdio, from a local checkout
claude mcp add -s user citewell -- uv --directory /path/to/citewell run citewell mcp
```
</details>

<details>
<summary><b>Claude Desktop</b> — <code>claude_desktop_config.json</code></summary>

Installed from PyPI — Claude Desktop does not see your shell's `PATH`, so use the full path that
`which citewell` prints (typically `~/.local/bin/citewell`):

```json
{
  "mcpServers": {
    "citewell": {
      "command": "/Users/you/.local/bin/citewell",
      "args": ["mcp"],
      "env": { "CITEWELL_DATABASE_URL": "postgresql://citewell:citewell@localhost:5432/citewell" }
    }
  }
}
```

With Docker Compose:

```json
{
  "mcpServers": {
    "citewell": {
      "command": "docker",
      "args": ["exec", "-i", "citewell-citewell-1", "citewell", "mcp"]
    }
  }
}
```

Local checkout:

```json
{
  "mcpServers": {
    "citewell": {
      "command": "uv",
      "args": ["--directory", "/path/to/citewell", "run", "citewell", "mcp"],
      "env": { "CITEWELL_DATABASE_URL": "postgresql://citewell:citewell@localhost:5432/citewell" }
    }
  }
}
```
</details>

<details>
<summary><b>Cursor</b> — <code>.cursor/mcp.json</code></summary>

```json
{ "mcpServers": { "citewell": { "url": "http://localhost:8000/mcp" } } }
```

or stdio with the PyPI install: `{ "mcpServers": { "citewell": { "command": "citewell", "args": ["mcp"] } } }`
</details>

### MCP surface

| Kind | Name | Purpose |
|---|---|---|
| tool | `search_documents(query, top_k, collection, mode, rerank, source_prefix)` | Cited passages (`ref`, `citation`, `source`, `page`, `chunk_id`, `quote`, `text`, `score`) |
| tool | `get_chunk(chunk_id, context)` | A chunk plus neighbouring chunks, to read around a quote |
| tool | `verify_quote(quote, chunk_id, source, collection)` | Checks that a quotation really occurs in the source; returns the exact wording and page, or the closest passage if it was paraphrased |
| tool | `list_collections()` / `list_documents(collection)` | What is indexed |
| resource | `citewell://collections`, `citewell://collections/{collection}/documents`, `citewell://chunks/{id}` | Same data as resources; collection names auto-complete |
| prompt | `answer_with_citations(question, collection)` | "Answer only from passages, cite with [n]" |

## CLI

```text
citewell init                         create extension + schema (idempotent)
citewell ingest PATH... [-c COL] [-l turkish|english|simple] [--force] [--prune [-y]]
citewell search "query" [-k 5] [-m hybrid|vector|keyword] [-c COL|*] [--rerank] [--json]
citewell verify "quote" [--chunk ID] [--source FILE] [-c COL]   exit code 4 if not found
citewell serve [--init] [--host] [--port]      REST API + MCP at /mcp
citewell mcp [--transport stdio|http]          MCP server only
citewell eval DATASET.jsonl [-k 5] [-r vector,keyword,hybrid,hybrid+rerank] [-o report.json]
citewell collections list|create|delete · documents list|delete · models download · doctor
```

## REST API

```bash
curl -s localhost:8000/v1/search -H 'content-type: application/json' \
  -d '{"query": "uzaktan çalışma kaç gün?", "top_k": 3, "mode": "hybrid"}'
curl -s -F file=@politika.pdf -F collection=handbook localhost:8000/v1/documents
```

`GET /health` · `POST|GET /v1/search` · `POST /v1/verify` · `GET /v1/chunks/{id}?context=1` · `GET|POST|DELETE /v1/collections` ·
`GET|POST|DELETE /v1/documents` — full schema at `/docs`. Set `CITEWELL_API_TOKEN` to require a bearer token.

## How it works

```mermaid
flowchart LR
  subgraph Ingest
    F[PDF / MD / TXT / HTML / DOCX] --> L[Loaders<br/>pages & sections]
    L --> C[Page-aware chunker<br/>verbatim slices]
    C --> E[bge-m3 embeddings<br/>+ title/section header]
  end
  E --> PG[(PostgreSQL<br/>pgvector HNSW<br/>tsvector GIN)]
  subgraph Query
    Q[query] --> V[vector top-40]
    Q --> K[keyword top-40<br/>turkish stemmer]
    V --> R[RRF k=60]
    K --> R
    R --> X[optional rerank<br/>bge-reranker-v2-m3]
    X --> O[passages + citations<br/>+ best quote]
  end
  PG --- V
  PG --- K
  O --> M[MCP · REST · CLI]
```

## Evaluation

```bash
citewell eval examples/eval/tr-sample.jsonl -k 5 -r vector,keyword,hybrid,hybrid+rerank --markdown
```

Datasets are JSON Lines: `{"id", "query", "relevant": [{"source", "page"?}], "collection"?}`.
Metrics: **Recall@k**, **MRR@k**, **Hit@k**, **Page hit@k** (exact page), **p50/p95 latency**.
CI runs the sample set end-to-end on every push (with the lexical test backends) and fails below a
recall floor; see [docs/evaluation.md](docs/evaluation.md).

### First results: Turkish Labour Law (İş Kanunu, 4857)

20 natural-language questions from [`examples/eval/mevzuat-questions.jsonl`](examples/eval/mevzuat-questions.jsonl)
against the official PDF from mevzuat.gov.tr (121 articles). A hit counts only if it lands on a page
of the right article. `BAAI/bge-m3` + `bge-reranker-v2-m3`, default chunking, Apple Silicon (MPS),
models already loaded:

| Run | Recall@5 | MRR@5 | Hit@5 | Page hit@5 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| vector | 1.000 | 0.885 | 1.000 | 1.000 | 45 | 95 |
| keyword | 0.850 | 0.614 | 0.850 | 0.850 | 8 | 11 |
| **hybrid** (default) | **1.000** | **0.893** | **1.000** | **1.000** | **48** | **54** |
| hybrid + rerank | 1.000 | 0.950 | 1.000 | 1.000 | 3259 | 3771 |

- Every question finds the right article **and page** in the top 5 with hybrid search; the right
  passage is usually ranked first or second (MRR 0.89).
- Dense retrieval does the heavy lifting on paraphrased questions; keyword search alone misses 15 %.
- The cross-encoder lifts MRR to 0.95 but costs ~3 s per query on a laptop, so it is opt-in
  (`--rerank` / `rerank: true`).

> Small and single-domain (20 questions, one law, written by the maintainers) — a first data point,
> not a leaderboard. Reproduce it with [docs/evaluation.md](docs/evaluation.md#turkish-legislation-set);
> larger independent Turkish eval sets are very welcome.

## Configuration

All settings are environment variables prefixed with `CITEWELL_` (or a `.env` file) — see
[`.env.example`](.env.example) and [docs/configuration.md](docs/configuration.md).

| Variable | Default |
|---|---|
| `CITEWELL_DATABASE_URL` | `postgresql://citewell:citewell@localhost:5432/citewell` |
| `CITEWELL_EMBEDDING_MODEL` / `_DIM` | `BAAI/bge-m3` / `1024` |
| `CITEWELL_RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` |
| `CITEWELL_DEFAULT_MODE` / `_TOP_K` | `hybrid` / `5` |
| `CITEWELL_CHUNK_SIZE` / `_OVERLAP` | `1000` / `150` characters |
| `CITEWELL_API_TOKEN` | unset (no auth; bind to localhost) |

## Roadmap

- [x] **0.1** — ingest (PDF/MD/TXT/HTML/DOCX), hybrid search (pgvector + tsvector, RRF), rerank,
  cited passages over CLI / REST / MCP, collections, Docker, Turkish eval sets
- [x] **0.2** — PyPI install, `verify_quote`, printed page labels, search without Turkish
  characters, MCP completions, `ingest --prune`
- [ ] **0.3** — OCR for scanned PDFs, better tables, `citewell watch`, more loaders, `doctor`
- [ ] **0.4** — OpenAI-compatible endpoint (Open WebUI), per-collection tokens
- [ ] **1.0** — stable API, public Turkish benchmark, sparse/BM25 retriever, SQLite mode

Details: [docs/roadmap.md](docs/roadmap.md) · progress in the [Roadmap issue](https://github.com/omerozkilic/citewell/issues/31) — `good first issue` and `help wanted` items are open for contributors.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Security reports: [SECURITY.md](SECURITY.md).
Architecture decisions live in [docs/adr](docs/adr/index.md).

## License

[MIT](LICENSE) © Ömer Özkılıç
