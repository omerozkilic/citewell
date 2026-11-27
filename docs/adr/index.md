# Architecture Decision Records

| ADR | Decision |
|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions |
| [0002](0002-no-llm-in-core.md) | No LLM in the core — return cited passages, not answers |
| [0003](0003-postgresql-pgvector.md) | PostgreSQL + pgvector + tsvector as the only datastore |
| [0004](0004-hybrid-search-rrf.md) | Hybrid retrieval with RRF, optional cross-encoder rerank |
| [0005](0005-local-multilingual-models.md) | Local multilingual models |
| [0006](0006-page-aware-chunking.md) | Page-aware chunking, verbatim slices, stable ids |
| [0007](0007-read-only-mcp.md) | MCP-first, read-only tool surface |
| [0008](0008-scoped-api-tokens.md) | Scoped API tokens (per-collection read/write) |
| [0009](0009-answerability-signal.md) | Answerability signal ("not in the documents") |
| [0010](0010-openai-compatible-adapter.md) | OpenAI-compatible chat adapter that returns passages |

New ADRs: copy [template.md](template.md).
