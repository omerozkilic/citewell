# CLI

`citewell --help` lists all commands. Human-readable output goes to stderr; `--json` output goes to
stdout, so it can be piped (`citewell search … --json | jq`).

| Command | Description |
|---|---|
| `citewell init` | Create the `vector` extension and apply migrations (idempotent). Records the embedding model and dimension. |
| `citewell ingest PATH… [-c COL] [-l LANG] [--force] [--no-recursive] [--prune [-y]]` | Load, chunk, embed and store files. Unchanged files are skipped. `--prune` also removes documents that are no longer in PATHS (asks first; never prunes when PATHS contain no files). Exit code 2 if any file failed. |
| `citewell search QUERY [-k N] [-m MODE] [-c COL]… [--rerank] [--json] [--full]` | Cited search results. `-c '*'` searches all collections. |
| `citewell verify QUOTE [--chunk ID] [--source FILE] [-c COL]… [--json]` | Check that a quotation occurs in the documents; prints the exact source wording and page. Exit code 4 if not verified. |
| `citewell serve [--init] [--host H] [--port P] [--no-mcp]` | REST API with the MCP Streamable HTTP endpoint at `/mcp`. |
| `citewell mcp [--transport stdio\|http]` | MCP server only (stdio for desktop clients). |
| `citewell eval DATASET [-k N] [-r RUNS] [-c COL] [-o FILE] [--markdown] [--fail-under X]` | Retrieval metrics; see [Evaluation](evaluation.md). Exit code 3 if hybrid Recall@k < X. |
| `citewell collections list\|create\|delete` | Manage collections (`create NAME -l english -d "…"`). |
| `citewell documents list\|delete` | List or remove documents by source path. |
| `citewell models download [--no-reranker]` | Fetch the configured models into the Hugging Face cache. |
| `citewell doctor` | Read-only install check: versions, database, pgvector, migrations, embedding dimension, model cache and offline readiness, with a fix hint per problem. `--json` for scripts; exit code 1 on failure. |

## Collections

A collection is an independent set of documents with its own **text-search language**
(`turkish`, `english` or `simple`). The language is set when the collection is created (first
ingest) and controls stemming and stop words for keyword search. Collection names are lowercase
`[a-z0-9_-]`, up to 64 characters.

```bash
citewell ingest ./ik -c ik                       # Turkish (default)
citewell ingest ./runbooks -c runbooks -l english
citewell search "on-call compensation" -c runbooks
citewell search "izin" -c ik -c runbooks         # several collections at once
```
