# REST API

`citewell serve` (and Docker Compose) exposes a FastAPI app on `http://127.0.0.1:8000`.
Interactive OpenAPI docs: `/docs`.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Status, version, database state, embedding model (never requires auth) |
| POST | `/v1/search` | Body: `query`, `top_k`, `mode`, `collections`, `rerank`, `source_prefix` |
| GET | `/v1/search?q=…&k=5&mode=hybrid&collection=…` | Same, as a query string |
| GET | `/v1/chunks/{chunk_id}?context=1` | Chunk with neighbours |
| GET | `/v1/collections` | List |
| POST | `/v1/collections` | `{"name": "hr", "language": "turkish", "description": "…"}` |
| DELETE | `/v1/collections/{name}` | Delete with all documents |
| GET | `/v1/documents?collection=…` | List |
| POST | `/v1/documents` | Multipart upload: `file`, optional `collection`, `language`, `force` |
| DELETE | `/v1/documents?collection=…&source=…` | Delete one document |
| POST | `/mcp` | MCP Streamable HTTP endpoint |

```bash
curl -s localhost:8000/v1/search -H 'content-type: application/json' \
  -d '{"query": "Parolam en az kaç karakter olmalı?", "top_k": 3}' | jq '.hits[] | {source, page, quote}'

curl -s -F file=@kvkk-politikasi.pdf -F collection=hukuk localhost:8000/v1/documents
```

Errors use standard status codes: `400` invalid input, `401` missing/invalid token, `404` unknown
collection/chunk, `413` upload too large, `415` unsupported file type.

## Authentication

Set `CITEWELL_API_TOKEN` to require `Authorization: Bearer <token>` on every endpoint except
`/health` — including `/mcp`.
