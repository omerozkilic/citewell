# ADR-0005: Local multilingual models (bge-m3 / multilingual-e5, bge-reranker-v2-m3)

- **Status:** Accepted
- **Date:** 2026-11-02

## Context

Turkish is the priority language; the tool must run offline without API keys.

## Decision

- Default embedding model: **`BAAI/bge-m3`** (1024-d, 8k context, strong multilingual/Turkish
  results). Supported alternative: **`intfloat/multilingual-e5-*`** — `query: ` / `passage: ` prefixes
  are applied automatically when the model name contains `e5`.
- Default reranker: **`BAAI/bge-reranker-v2-m3`**, scores mapped through a sigmoid to (0, 1).
- Models run through `sentence-transformers` (optional `models` extra, CPU PyTorch in Docker), are
  downloaded once with `citewell models download`, and then work with `HF_HUB_OFFLINE=1`.
- A deterministic `hash` embedder and `lexical` reranker exist for tests/CI only.
- Each embedded chunk is prefixed with its document title and section ("contextual chunk headers").

## Consequences

- No network or key at query time; first-time download is ~2–3 GB.
- CPU inference of bge-m3 is the main ingest bottleneck; GPU/MPS is picked up automatically when
  available (`CITEWELL_EMBEDDING_DEVICE`).
