# Citewell

**Citation-grounded document memory for AI assistants.** Offline · MCP-native · Turkish-ready.

Citewell is a headless retrieval server. It ingests your PDFs, Markdown, text, HTML and Word files
into PostgreSQL + pgvector and serves **cited passages** — file, page, chunk id and a verbatim quote —
to AI assistants over the [Model Context Protocol](https://modelcontextprotocol.io), a CLI and a REST
API.

It never calls an LLM and needs no API key: your assistant (Claude, Cursor, …) writes the answer,
Citewell makes sure it can point at the source.

<div class="grid cards" markdown>

- **[Getting started](getting-started.md)** — `docker compose up`, ingest, search.
- **[Connect an assistant](mcp-clients.md)** — Claude Code, Claude Desktop, Cursor.
- **[Architecture](architecture.md)** — ingest and query pipelines, data model.
- **[Evaluation](evaluation.md)** — Recall@k, MRR, page hit rate, latency.

</div>

## What a search returns

```json
{
  "ref": "[1]",
  "citation": "calisan-el-kitabi.pdf, s. 4",
  "source": "calisan-el-kitabi.pdf",
  "page": 4,
  "chunk_id": "c9a6068735629cb0647e",
  "score": 0.0328,
  "quote": "İş seyahatlerinde konaklama için gecelik üst sınır İstanbul, Ankara ve İzmir'de 3.500 TL, diğer şehirlerde 2.500 TL'dir.",
  "text": "4. Masraf ve Seyahat\nİş seyahatlerinde konaklama için …"
}
```
