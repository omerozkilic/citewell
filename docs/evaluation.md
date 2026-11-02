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

The bundled 35-question set is small and was written alongside the corpus — treat it as a smoke
test. Results with `BAAI/bge-m3` and `bge-reranker-v2-m3` on a larger, independent Turkish dataset
will be published here. Contributions of real-world eval sets (with permissively licensed documents)
are very welcome.
