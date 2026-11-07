# Roadmap

Releases follow [semantic versioning](https://semver.org/) via release-please; before 1.0, new
features bump the minor version. Track progress in
[GitHub issues and milestones](https://github.com/omerozkilic/citewell/milestones).

## 0.1 — foundations ✅
- Loaders: PDF, Markdown, TXT, HTML, DOCX; page-aware chunking; idempotent ingest
- Hybrid search: pgvector + PostgreSQL full-text (Turkish stemming), RRF fusion, optional
  cross-encoder rerank (`bge-reranker-v2-m3`)
- Cited passages over CLI, REST API and MCP (stdio + Streamable HTTP); Docker Compose
- Multiple collections with per-collection language; MCP resources and the citation prompt
- Eval harness (Recall@k, MRR, page hit, latency) with Turkish handbook and legislation sets

## 0.2 — citation quality & Turkish (next release)
- [x] Install from PyPI (`uv tool install "citewell[models]"`), no clone needed
- [x] `verify_quote`: check a quotation against the source, get the exact wording and page
- [x] Printed PDF page labels in citations (`s. 12 (PDF s. 17)`)
- [x] Search without Turkish characters (`ogrenci izni` → `öğrenci izni`)
- [x] MCP argument completion for collection names; per-collection documents resource
- [x] `ingest --prune` keeps a collection in sync with a folder
- [x] Workflow actions pinned to commit SHAs

## 0.3 — more document types
- [ ] OCR for scanned PDFs (Tesseract `tur`)
- [ ] Better tables in PDFs
- [ ] `citewell watch`: re-index a folder when files change
- [ ] Complete the legislation eval with KVKK and the Constitution

## 0.4 — UI bridge & sharing
- [ ] OpenAI-compatible `/v1/chat/completions` adapter so UIs like Open WebUI can use Citewell
  (generation delegated to a user-configured model; the core stays LLM-free — needs an ADR)
- [ ] Per-collection tokens / read scopes for the HTTP endpoint
- [ ] Progress notifications for long MCP operations

## 1.0 and later
- Stable API and MCP tool contracts
- Public Turkish retrieval benchmark
- Sparse / BM25 retriever as a third ranking
- SQLite single-file mode for zero-dependency installs
