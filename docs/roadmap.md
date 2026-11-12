# Roadmap

Releases follow [semantic versioning](https://semver.org/) via release-please; before 1.0, new
features bump the minor version. The overview lives in the
[Roadmap issue (#31)](https://github.com/omerozkilic/citewell/issues/31); each item has its own issue
and [milestone](https://github.com/omerozkilic/citewell/milestones). Issues labelled
`good first issue` or `help wanted` are good places to start.

## 0.1 — foundations ✅
- Loaders: PDF, Markdown, TXT, HTML, DOCX; page-aware chunking; idempotent ingest
- Hybrid search: pgvector + PostgreSQL full-text (Turkish stemming), RRF fusion, optional
  cross-encoder rerank (`bge-reranker-v2-m3`)
- Cited passages over CLI, REST API and MCP (stdio + Streamable HTTP); Docker Compose
- Multiple collections with per-collection language; MCP resources and the citation prompt
- Eval harness (Recall@k, MRR, page hit, latency) with Turkish handbook and legislation sets

## 0.2 — citation quality & Turkish ✅
- [x] Install from PyPI (`uv tool install "citewell[models]"`), no clone needed ([#10](https://github.com/omerozkilic/citewell/issues/10))
- [x] `verify_quote`: check a quotation against the source, get the exact wording and page ([#11](https://github.com/omerozkilic/citewell/issues/11))
- [x] Printed PDF page labels in citations (`s. 12 (PDF s. 17)`) ([#12](https://github.com/omerozkilic/citewell/issues/12))
- [x] Search without Turkish characters (`ogrenci izni` → `öğrenci izni`) ([#13](https://github.com/omerozkilic/citewell/issues/13))
- [x] MCP argument completion for collection names; per-collection documents resource ([#14](https://github.com/omerozkilic/citewell/issues/14))
- [x] `ingest --prune` keeps a collection in sync with a folder ([#15](https://github.com/omerozkilic/citewell/issues/15))
- [x] Workflow actions pinned to commit SHAs ([#16](https://github.com/omerozkilic/citewell/issues/16))

## 0.3 — more document types
- [x] OCR for scanned PDFs (Tesseract `tur`) ([#17](https://github.com/omerozkilic/citewell/issues/17))
- [x] Better tables in PDFs ([#18](https://github.com/omerozkilic/citewell/issues/18))
- [x] `citewell watch`: re-index a folder when files change ([#19](https://github.com/omerozkilic/citewell/issues/19))
- [ ] Complete the legislation eval with KVKK and the Constitution ([#20](https://github.com/omerozkilic/citewell/issues/20))
- [ ] List Citewell in the official MCP Registry ([#21](https://github.com/omerozkilic/citewell/issues/21))
- [ ] More Turkish eval questions ([#22](https://github.com/omerozkilic/citewell/issues/22))
- [x] `citewell doctor`: diagnose the install ([#35](https://github.com/omerozkilic/citewell/issues/35))
- [x] More loaders: EPUB, PPTX, XLSX/CSV, EML ([#36](https://github.com/omerozkilic/citewell/issues/36))
- [ ] CI eval regression gate ([#38](https://github.com/omerozkilic/citewell/issues/38))
- [ ] Security: Query limits and DB statement timeout ([#48](https://github.com/omerozkilic/citewell/issues/48))
- [ ] Security: Container hardening in compose.yaml ([#49](https://github.com/omerozkilic/citewell/issues/49))
- [ ] Security: Supply chain: pip-audit, SBOM and build provenance ([#50](https://github.com/omerozkilic/citewell/issues/50))
- [ ] Security: Parser hardening and model revision pinning ([#51](https://github.com/omerozkilic/citewell/issues/51))

## 0.4 — UI bridge & sharing
- [ ] OpenAI-compatible `/v1/chat/completions` adapter so UIs like Open WebUI can use Citewell ([#23](https://github.com/omerozkilic/citewell/issues/23))
  (generation delegated to a user-configured model; the core stays LLM-free — needs an ADR)
- [ ] Per-collection tokens / read scopes for the HTTP endpoint ([#24](https://github.com/omerozkilic/citewell/issues/24)) — also covers rate limiting and an optional audit log
- [ ] Progress notifications for long MCP operations ([#25](https://github.com/omerozkilic/citewell/issues/25))
- [ ] Metadata filters in search ([#39](https://github.com/omerozkilic/citewell/issues/39))
- [ ] Export citations (BibTeX, CSL-JSON, Markdown footnotes) ([#40](https://github.com/omerozkilic/citewell/issues/40))
- [ ] Answerability signal ("not in the documents") ([#41](https://github.com/omerozkilic/citewell/issues/41))
- [ ] Minimal web UI at `/ui` ([#42](https://github.com/omerozkilic/citewell/issues/42))
- [ ] Prometheus `/metrics` ([#43](https://github.com/omerozkilic/citewell/issues/43))

## 1.0 and later
- Stable API and MCP tool contracts ([#26](https://github.com/omerozkilic/citewell/issues/26))
- Public Turkish retrieval benchmark ([#27](https://github.com/omerozkilic/citewell/issues/27))
- Sparse / BM25 retriever as a third ranking ([#28](https://github.com/omerozkilic/citewell/issues/28))
- SQLite single-file mode for zero-dependency installs ([#29](https://github.com/omerozkilic/citewell/issues/29))
- Windows install guide and CI check ([#30](https://github.com/omerozkilic/citewell/issues/30))
- Document versioning ("as of version X") ([#44](https://github.com/omerozkilic/citewell/issues/44))
- Turkish legal-reference parser ([#45](https://github.com/omerozkilic/citewell/issues/45))
- Duplicate and conflict finder ([#46](https://github.com/omerozkilic/citewell/issues/46))
- Ready-made collection packs ([#47](https://github.com/omerozkilic/citewell/issues/47))
