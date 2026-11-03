# Roadmap

## v0.1 — foundations ✅
- Loaders: PDF, Markdown, TXT, HTML, DOCX; page-aware chunking; idempotent ingest
- Vector search (pgvector HNSW) with cited passages
- CLI, REST API, MCP (stdio + Streamable HTTP), Docker Compose

## v0.2 — quality ✅
- Hybrid search: pgvector + PostgreSQL full-text (Turkish stemming), RRF fusion
- Optional cross-encoder rerank (`bge-reranker-v2-m3`)
- Eval harness (Recall@k, MRR, page hit, latency) and a Turkish sample set in CI

## v0.3 — MCP & multi-tenant
- [x] Multiple collections with per-collection language
- [x] MCP resources (`citewell://…`) and the `answer_with_citations` prompt
- [ ] Argument completions for collection names
- [ ] Progress notifications for long operations
- [ ] Per-collection tokens / read scopes for the HTTP endpoint

## Later
- OpenAI-compatible `/v1/chat/completions` adapter so UIs like Open WebUI can use Citewell
  (generation delegated to a user-configured model; core stays LLM-free)
- OCR for scanned PDFs (Tesseract `tur`)
- Accent-insensitive Turkish matching; sparse / BM25 retriever as a third ranking
- Public Turkish retrieval benchmark
- SQLite single-file mode for zero-dependency installs
