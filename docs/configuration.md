# Configuration

Settings are read from environment variables prefixed with `CITEWELL_` and from a `.env` file in the
working directory. See `.env.example` in the repository.

## Storage

| Variable | Default | Notes |
|---|---|---|
| `CITEWELL_DATABASE_URL` | `postgresql://citewell:citewell@localhost:5432/citewell` | pgvector must be installable |
| `CITEWELL_POOL_MIN_SIZE` / `_MAX_SIZE` | `1` / `8` | psycopg connection pool |

## Embeddings and reranking

| Variable | Default | Notes |
|---|---|---|
| `CITEWELL_EMBEDDING_BACKEND` | `sentence-transformers` | `hash` = lexical test stand-in |
| `CITEWELL_EMBEDDING_MODEL` | `BAAI/bge-m3` | or `intfloat/multilingual-e5-large` / `-base` |
| `CITEWELL_EMBEDDING_DIM` | `1024` | **fixed per database** (768 for e5-base) |
| `CITEWELL_EMBEDDING_DEVICE` | auto | `cpu`, `cuda`, `mps` |
| `CITEWELL_EMBEDDING_BATCH_SIZE` | `16` | |
| `CITEWELL_MAX_SEQ_LENGTH` | `512` | tokens per chunk passed to the model |
| `CITEWELL_RERANKER_BACKEND` | `sentence-transformers` | `none` disables, `lexical` = test stand-in |
| `CITEWELL_RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | |
| `CITEWELL_RERANK_BY_DEFAULT` | `false` | clients can still pass `rerank=true` |
| `CITEWELL_RERANK_CANDIDATES` | `30` | how many fused candidates are reranked |

The embedding model and dimension are recorded in the database at `citewell init`; Citewell refuses
to start with a different configuration rather than silently mixing incompatible vectors.

## Chunking and search

| Variable | Default | Notes |
|---|---|---|
| `CITEWELL_CHUNK_SIZE` | `1000` | characters |
| `CITEWELL_CHUNK_OVERLAP` | `150` | characters, whole sentences |
| `CITEWELL_MIN_CHUNK_SIZE` | `40` | tiny tails are merged into the previous chunk |
| `CITEWELL_DEFAULT_COLLECTION` | `default` | |
| `CITEWELL_DEFAULT_LANGUAGE` | `turkish` | for new collections |
| `CITEWELL_DEFAULT_MODE` | `hybrid` | |
| `CITEWELL_DEFAULT_TOP_K` / `_MAX_TOP_K` | `5` / `50` | |
| `CITEWELL_CANDIDATE_POOL` | `40` | per retriever, before fusion |
| `CITEWELL_RRF_K` | `60` | RRF constant |
| `CITEWELL_QUOTE_MAX_CHARS` | `320` | |

## Servers

| Variable | Default | Notes |
|---|---|---|
| `CITEWELL_HOST` / `_PORT` | `127.0.0.1` / `8000` | Docker image uses `0.0.0.0` (port published on localhost) |
| `CITEWELL_API_TOKEN` | unset | bearer token for REST and HTTP MCP |
| `CITEWELL_ALLOWED_HOSTS` | `[]` | extra `Host` values for DNS-rebinding protection, JSON list, e.g. `["citewell:*"]` |
| `CITEWELL_MAX_UPLOAD_MB` | `50` | |
| `CITEWELL_LOG_LEVEL` | `INFO` | |
| `CITEWELL_PRELOAD_MODELS` | `true` | `serve` / `mcp` load the embedding model in the background at startup |

## Offline mode

After `citewell models download`, set `HF_HUB_OFFLINE=1` (and optionally `TRANSFORMERS_OFFLINE=1`) to
guarantee no requests are made to the Hugging Face Hub. Citewell itself makes no outbound requests.
