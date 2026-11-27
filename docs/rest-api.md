# REST API

`citewell serve` (and Docker Compose) exposes a FastAPI app on `http://127.0.0.1:8000`.
Interactive OpenAPI docs: `/docs`.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Status, version, database state, embedding model (never requires auth) |
| POST | `/v1/search` | Body: `query`, `top_k`, `mode`, `collections`, `rerank`, `source_prefix`, `filters` ([metadata filters](#metadata-filters)) |
| GET | `/v1/search?q=…&k=5&mode=hybrid&collection=…` | Same, as a query string; filters as `type`, `author`, `date_from`, `date_to`, `tag` (repeatable) |
| POST | `/v1/verify` | Body: `quote`, optional `chunk_id`, `source`, `collections` — checks a quotation against the source |
| GET | `/v1/chunks/{chunk_id}?context=1` | Chunk with neighbours |
| GET | `/v1/collections` | List |
| POST | `/v1/collections` | `{"name": "hr", "language": "turkish", "description": "…"}` |
| DELETE | `/v1/collections/{name}` | Delete with all documents |
| GET | `/v1/documents?collection=…` | List |
| POST | `/v1/documents` | Multipart upload: `file`, optional `collection`, `language`, `force`, `tags` (repeatable) |
| DELETE | `/v1/documents?collection=…&source=…` | Delete one document |
| POST | `/mcp` | MCP Streamable HTTP endpoint |

```bash
curl -s localhost:8000/v1/search -H 'content-type: application/json' \
  -d '{"query": "Parolam en az kaç karakter olmalı?", "top_k": 3}' | jq '.hits[] | {source, page, quote}'

curl -s -F file=@kvkk-politikasi.pdf -F collection=hukuk localhost:8000/v1/documents
```

Errors use standard status codes: `400` invalid input, `401` missing/invalid token, `403` outside the token's scope, `429` rate limit exceeded (`CITEWELL_RATE_LIMIT_PER_MINUTE`), `404` unknown
collection/chunk, `413` upload too large, `415` unsupported file type.

## Authentication

Set `CITEWELL_API_TOKEN` to require `Authorization: Bearer <token>` on every endpoint except
`/health` — including `/mcp`.

### Scoped tokens

`citewell tokens create NAME -c COLLECTION [-c ...] [--write]` (or `--all-collections`) makes a token
limited to those collections; `tokens list` and `tokens revoke NAME` manage them. Only a hash is stored
and the secret is shown once. A scoped token can search, verify, read chunks and list the collections
and documents it may see; `--write` additionally allows `POST /v1/documents`, `POST /v1/collections`
and the DELETE endpoints, still only inside its collections. Anything else returns `403`. Searches
without a collection use the default collection when the token may read it, `"*"` means all of its
collections. `CITEWELL_API_TOKEN` stays unrestricted. Once any scoped token exists, the server rejects
requests without a valid token even if `CITEWELL_API_TOKEN` is unset.

## Metadata filters

Searches can be narrowed to documents by file type, author, date or tags. All conditions must hold, and
they are applied inside the database query for vector, keyword and hybrid search alike, so you still get
`top_k` results when enough documents match.

| Filter (`filters` object / query string) | Meaning |
|---|---|
| `file_types` / `type` | Extensions such as `pdf`, `docx`; a document matches if it has any of them |
| `author` | Part of the author name, case-insensitive (Turkish-aware: `İlker` = `ilker`) |
| `date_from`, `date_to` | Document date range, `YYYY-MM-DD`, inclusive |
| `tags` / `tag` | Tags the document must all carry |

```bash
curl -s localhost:8000/v1/search -H 'content-type: application/json' \
  -d '{"query": "izin", "filters": {"file_types": ["pdf"], "date_from": "2024-01-01", "tags": ["ik"]}}'
```

Where the values come from: **author** and **date** are read from the file itself when it has them
(PDF info dictionary, DOCX/PPTX/XLSX core properties, the `From` and `Date` headers of an EML) and shown by
`GET /v1/documents` and `citewell documents list --json` as `author` and `doc_date`; **tags** are set at
ingest time (`citewell ingest --tag NAME`, or `tags` on the upload). Documents without a date never match a
date filter. Existing documents get their author from the upgrade; re-ingest with `--force` to pick up dates
or to change tags (an unchanged file is otherwise skipped).
