# Evaluation

Retrieval quality is measured, not assumed. `citewell eval` runs a JSONL dataset against one or
more retrieval configurations.

```bash
citewell eval examples/eval/tr-sample.jsonl -k 5 \
  -r vector,keyword,hybrid,hybrid+rerank --markdown -o eval-report.json
```

## Dataset format

One JSON object per line (`//` comment lines are ignored):

```json
{"id": "tr12", "query": "Ankara'da otelde bir gece için en fazla ne kadar harcayabilirim?",
 "relevant": [{"source": "calisan-el-kitabi.pdf", "page": 4}],
 "collection": "default", "tags": ["paraphrase"]}
```

- `source` is the document path as stored (relative to the ingest root).
- `page` is optional; omit it for unpaged formats or to accept any page.
- `collection` falls back to `--collection`, then to the default collection.

## Metrics

| Metric | Definition |
|---|---|
| Recall@k | Fraction of a query's relevant items found in the top k, averaged over queries |
| MRR@k | Mean of 1 / rank of the first relevant hit (0 if none in the top k) |
| Hit@k | Fraction of queries with at least one relevant hit in the top k |
| Page hit@k | Among queries with paged relevant items: fraction with a hit on the exact page |
| Doc hit@k | Like Hit@k but ignores pages (in the JSON report) |
| Latency | p50 / p95 / mean end-to-end search time (ms), after one warm-up query |

The JSON report includes per-query ranks and top results for error analysis.

## In CI

The `eval` job ingests the sample corpus with the lexical `hash` embedder and fails if hybrid
Recall@5 drops below 0.8 (`--fail-under`). This guards the *pipeline* (loaders, chunking, SQL,
fusion) on every push; it says nothing about semantic quality.

## Benchmarks

The bundled 35-question handbook set was written alongside the corpus — treat it as a smoke test.

### Turkish Labour Law (4857) — 2026-11-03

20 questions from `examples/eval/mevzuat-questions.jsonl`, official mevzuat.gov.tr PDF (121
articles), `BAAI/bge-m3` + `BAAI/bge-reranker-v2-m3`, chunk size 1000 / overlap 150, k = 5,
Apple Silicon (MPS), latency measured after model warm-up:

| Run | Recall@5 | MRR@5 | Hit@5 | Page hit@5 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|
| vector | 1.000 | 0.885 | 1.000 | 1.000 | 45 | 95 |
| keyword | 0.850 | 0.614 | 0.850 | 0.850 | 8 | 11 |
| **hybrid** (default) | **1.000** | **0.893** | **1.000** | **1.000** | **48** | **54** |
| hybrid + rerank | 1.000 | 0.950 | 1.000 | 1.000 | 3259 | 3771 |

Small and single-domain; KVKK and Constitution questions were not included in this run.
Contributions of real-world eval sets (with permissively licensed documents) are very welcome.

## Turkish legislation set

`examples/eval/mevzuat-questions.jsonl` contains 35 questions about the Labour Law (4857), the
Personal Data Protection Law (KVKK, 6698) and the Constitution (2709). Each question names a law
and an article instead of a page, because page numbers change whenever mevzuat.gov.tr republishes
an amended text. Turkish legislation is not protected by copyright (FSEK art. 31), which makes it a
good basis for a public benchmark.

1. Download the PDFs from mevzuat.gov.tr into one folder (e.g. `data/mevzuat/`); keep the law
   number in the file name (`1.5.4857.pdf`, `is-kanunu-4857.pdf`, …).
2. Ingest them and build the dataset for *your* PDF versions. The script finds each
   `Madde N –` heading with the same extraction Citewell uses and records every page the article
   spans (`"pages": [27, 28]` — a hit on any of them counts):

```bash
uv run citewell ingest data/mevzuat -c mevzuat
uv run python scripts/build_mevzuat_eval.py data/mevzuat -o data/mevzuat-eval.jsonl
uv run citewell eval data/mevzuat-eval.jsonl -c mevzuat -r vector,keyword,hybrid,hybrid+rerank --markdown
```

Questions whose law PDF is missing are skipped, so you can start with the Labour Law alone.
