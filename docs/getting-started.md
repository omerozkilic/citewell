# Getting started

## From PyPI (quickest)

Requirements: Python 3.11+ and [uv](https://docs.astral.sh/uv/) (or pipx), plus Docker or any
PostgreSQL 15+ with [pgvector](https://github.com/pgvector/pgvector).

```bash
uv tool install "citewell[models]"
docker run -d --name citewell-db -p 127.0.0.1:5432:5432 \
  -e POSTGRES_USER=citewell -e POSTGRES_PASSWORD=citewell -e POSTGRES_DB=citewell \
  -v citewell-pgdata:/var/lib/postgresql/data pgvector/pgvector:pg17
citewell init
citewell models download
citewell ingest ~/Documents/policies -c policies
```

`uv tool upgrade citewell` updates it later. Then [connect an assistant](mcp-clients.md).

!!! note "Linux servers without a GPU"
    PyTorch from PyPI ships CUDA libraries (several GB) on Linux. On a CPU-only server the Docker
    image below is lighter, since it uses CPU-only PyTorch.

## With Docker (REST + HTTP MCP server)

Requirements: Docker with Compose v2. About 4 GB of disk for the image and models.

```bash
git clone https://github.com/omerozkilic/citewell && cd citewell
docker compose up -d
```

This starts PostgreSQL 17 with pgvector and the Citewell server on `127.0.0.1:8000`
(REST + MCP). The schema is created automatically (`serve --init`).

Download the models once (internet required), then everything runs offline:

```bash
docker compose run --rm citewell models download
```

Put documents into `./data` (mounted read-only at `/data`) and ingest them:

```bash
docker compose run --rm citewell ingest /data                     # default collection
docker compose run --rm citewell ingest /data/hr -c hr            # a separate collection
docker compose run --rm citewell search "yıllık izin kaç gün?" -c hr
```

Ingest is idempotent: unchanged files are skipped by SHA-256, changed files are replaced atomically.

!!! tip "Sample corpus"
    `examples/corpus` contains a fictional Turkish company handbook (PDF + Markdown) and
    `examples/eval/tr-sample.jsonl` has 35 questions about it:

    ```bash
    docker compose run --rm -v ./examples:/examples:ro citewell ingest /examples/corpus
    docker compose run --rm -v ./examples:/examples:ro citewell eval /examples/eval/tr-sample.jsonl
    ```

## Without Docker

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), PostgreSQL 15+ with
[pgvector](https://github.com/pgvector/pgvector) ≥ 0.7 (0.8+ recommended).

```bash
uv sync --extra models          # sentence-transformers + PyTorch
docker compose up -d db         # or point CITEWELL_DATABASE_URL at your own PostgreSQL
uv run citewell init
uv run citewell models download
uv run citewell ingest ~/Documents/policies
uv run citewell serve           # http://127.0.0.1:8000/docs and /mcp
```

Run `citewell doctor` at any time to check the database, pgvector version, schema and models.

## Supported formats

| Format | Location in citations |
|---|---|
| PDF (text layer) | page number; plus the printed page label when the PDF defines one that differs (e.g. `s. 12 (PDF s. 17)`, `s. iv`) |
| Plain text | page number if the file contains form feeds (`pdftotext` output), otherwise none |
| Markdown | heading path, e.g. `Bilgi Güvenliği Politikası > Parola Kuralları` |
| DOCX (`citewell[docx]`) | heading |
| PPTX | slide number, plus the slide's first line as its title (speaker notes are not indexed) |
| XLSX | sheet name; rows become lines with cells separated by ` | ` (hidden sheets are skipped, dates stay as stored numbers) |
| CSV | – (rows as lines; `,` `;` tab and `\|` delimiters and legacy Turkish encodings are detected) |
| EPUB | chapter title |
| EML | subject; headers (subject, from, to, date) are part of the indexed text, attachments are not |
| HTML | – |

PPTX, XLSX, CSV, EPUB and EML need no extra install. Legacy binary Office files (`.doc`, `.xls`, `.ppt`) are not supported.

Scanned PDFs without a text layer are reported as `skipped`; OCR is on the roadmap.
