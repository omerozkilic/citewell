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

It also compares every run with a stored baseline (`examples/eval/baselines/*.json`) and fails when
Recall@k, MRR@k or page hit drop by more than `--tolerance` (default 0.02), so a retrieval change that
quietly makes things worse cannot be merged. The comparison table ends up in the job summary.

```bash
citewell eval questions.jsonl -r hybrid --write-baseline baseline.json   # record
citewell eval questions.jsonl -r hybrid --baseline baseline.json         # compare, exit 3 on regression
```

See [CONTRIBUTING](https://github.com/omerozkilic/citewell/blob/main/CONTRIBUTING.md) for refreshing the
baselines after an intentional change.

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

## Queries without Turkish characters

`examples/eval/tr-sample-ascii.jsonl` repeats the handbook questions typed without Turkish
characters (`Haftalik standart calisma suresi kac saat?`). Keyword search runs on a
diacritic-folded index; on this set (hash test embedder) it lifted keyword Recall@5 from 0.829 to
0.943 and hybrid MRR@5 from 0.808 to 0.907. CI checks it on every push.

## Turkish legislation set

`examples/eval/mevzuat-questions.jsonl` contains 53 questions about the Labour Law (4857, 20), the
Personal Data Protection Law (KVKK, 6698, 16) and the Constitution (2709, 17). Each question names a law
and an article instead of a page, because page numbers change whenever mevzuat.gov.tr republishes
an amended text. Turkish legislation is not protected by copyright (FSEK art. 31), which makes it a
good basis for a public benchmark.

1. Download the PDFs into one folder (e.g. `data/mevzuat/`); keep the law number in the file name
   (`1.5.4857.pdf`, `is-kanunu-4857.pdf`, …). mevzuat.gov.tr is the primary source; it is sometimes
   unreachable from outside Turkey. The Constitution is also published as a PDF by the Grand National
   Assembly (`https://cdn.tbmm.gov.tr/TbmmWeb/Anayasa/anayasa_2018.pdf`; save it as `anayasa-2709.pdf`). Name
   the KVKK export `1.5.6698.pdf`.
2. Ingest them and build the dataset for *your* PDF versions. The script finds each
   `Madde N –` heading with the same extraction Citewell uses and records every page the article
   spans (`"pages": [27, 28]` — a hit on any of them counts):

```bash
uv run citewell ingest data/mevzuat -c mevzuat
uv run python scripts/build_mevzuat_eval.py data/mevzuat -o data/mevzuat-eval.jsonl
uv run citewell eval data/mevzuat-eval.jsonl -c mevzuat -r vector,keyword,hybrid,hybrid+rerank --markdown
```

Questions whose law PDF is missing are skipped, so you can start with the Labour Law alone.

The KVKK and Constitution questions were checked against real PDFs: every question resolves to its article
and the article text answers it. Mind the version of the KVKK text: articles 6, 9 and 18 were rewritten in
2024 (Law 7499). The questions about them (`kv02`, `kv05`) stay valid, but the answer differs between a
pre-2024 and a current PDF, so compare runs only within one PDF version. Question tags (`exact`,
`paraphrase`, `numbers`, `reasoning`, `cross-reference`) let you see where retrieval struggles.
