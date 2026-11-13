# CLAUDE.md — working on Citewell

Citewell is a headless RAG server: it ingests documents into PostgreSQL + pgvector and returns
**cited passages** (file, page, chunk id, verbatim quote) over MCP, a CLI and a REST API. It has
**no LLM calls of its own** and must keep working fully offline.

## Commands

```bash
uv sync --group dev                       # install (+ --extra models for sentence-transformers)
uv run ruff check . && uv run ruff format --check . && uv run mypy src   # lint + strict types
CITEWELL_TEST_DATABASE_URL=postgresql://citewell:citewell@localhost:5432/citewell_test uv run pytest --cov
docker compose up -d db                   # pgvector database for local work
CITEWELL_TEST_DATABASE_URL=… scripts/check_patch_coverage.sh   # patch coverage vs origin/main, must be ≥ 95 %
```

For quick end-to-end checks without model downloads:
`CITEWELL_EMBEDDING_BACKEND=hash CITEWELL_RERANKER_BACKEND=lexical`.

## Layout (src/citewell)

- `loaders.py` → `chunking.py` → `ingest.py` → `store.py` (write path)
- `search.py` (vector / keyword / hybrid RRF + optional rerank) → `store.py` (read path)
- `mcp_server.py` (MCP tools/resources/prompts), `api.py` (FastAPI + MCP mounted at /mcp), `cli.py` (Typer)
- `app.py` wires settings, pool and lazily-loaded models; `config.py` = `CITEWELL_*` settings
- `evaluation.py` = Recall@k, MRR, page hit, latency; datasets in `examples/eval/*.jsonl`
- `migrations/NNNN_*.sql` applied by `db.migrate` (`{dim}` placeholder = embedding dimension)

## Rules

- Never add an LLM/API-key dependency to the core. Offline by default.
- MCP tools stay read-only (see SECURITY.md, ADR-0007). Treat document text as untrusted.
- Chunk text must remain a verbatim slice of page text; chunks never cross pages (ADR-0006).
- Turkish first: use `text.tr_lower` instead of `str.lower` for anything that is indexed or matched.
- Schema changes = new numbered migration file; never edit an applied migration.
- Retrieval changes: report `citewell eval` before/after in the PR.
- mcp SDK is v2 (`mcp.server.mcpserver.MCPServer`, not v1 `FastMCP`). Modules that register MCP tools
  or FastAPI dependencies must not use `from __future__ import annotations` (annotations are evaluated
  at registration time).
- Conventional Commits; architecture decisions get an ADR in `docs/adr/`.
- **Codecov must pass.** The `codecov/patch` check fails a PR whose changed lines are covered less than the
  project is (~92 %). Every new or changed line needs a test, including error paths and CLI output. Before
  pushing, run `scripts/check_patch_coverage.sh` **with a test database** (without one, database-backed lines
  look uncovered, so the number is wrong); it must report ≥ 95 % and lists each missing line. Don't push a
  branch that fails it, and don't lower thresholds or exclude code to get around it.
