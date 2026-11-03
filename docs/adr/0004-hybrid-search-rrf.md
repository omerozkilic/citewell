# ADR-0004: Hybrid retrieval fused with Reciprocal Rank Fusion, optional cross-encoder rerank

- **Status:** Accepted
- **Date:** 2026-11-02

## Context

Dense retrieval handles paraphrases and cross-lingual queries; lexical retrieval handles exact terms,
numbers, codes and names (e.g. "KVKK", "3.500 TL", article numbers). Neither alone is reliable,
especially for Turkish.

## Decision

- Run the vector and keyword retrievers independently (top `candidate_pool` each, default 40).
- Fuse with **Reciprocal Rank Fusion**: `score(d) = Σ 1 / (k + rank_i(d))`, `k = 60`.
- When collections with different text-search languages are searched together, each language
  contributes its own keyword ranking to RRF.
- Optionally rerank the top `rerank_candidates` (default 30) with a cross-encoder
  (`BAAI/bge-reranker-v2-m3`), off by default because it is the slowest stage on CPU.
- Expose `vector`, `keyword` and `hybrid` modes everywhere so the eval harness can compare them.

## Consequences

- RRF needs no score normalisation or tuning and is robust to the different score scales of cosine
  similarity and `ts_rank_cd`.
- Keyword queries use OR semantics over stemmed lexemes (`a | b | c`) instead of
  `websearch_to_tsquery`'s AND, because natural-language questions rarely contain every term.

## Alternatives considered

- Weighted linear score fusion — needs per-corpus normalisation and tuning.
- Learned sparse retrieval (SPLADE / bge-m3 sparse) — promising follow-up; would plug in as a third
  ranking in RRF.
