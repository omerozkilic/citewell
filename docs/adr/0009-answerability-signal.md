# ADR-0009: Answerability signal ("not in the documents")

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

Retrieval always returns the nearest passages, even when none of them answers the question, and an
assistant that sees passages tends to answer anyway. The core must stay free of LLM calls (ADR-0002) and
work offline.

## Decision

- Every search returns `confidence` (0-1) and `answerable`. **Confidence** is the best *term coverage* among
  the returned passages: the share of the query's content words (stop words and question words removed,
  Turkish-aware prefix stems, diacritics folded) found in a passage. With a reranker, the best reranker
  probability is used when it is higher. `answerable` is `confidence >= CITEWELL_ANSWERABLE_THRESHOLD`
  (default 0.35; 0 turns the signal off).
- It is advice, not a filter: passages are always returned. MCP gives it as `answerable`, `confidence` and
  a `note`, and the server instructions tell assistants to say so instead of guessing.
- The signal is lexical on purpose: it does not depend on the embedding model, so it behaves the same
  with the offline backends and can be reproduced in CI.
- `examples/eval/unanswerable.jsonl` (28 questions the sample corpora do not answer, reusing corpus
  vocabulary) and `answerable: false` queries in eval datasets measure it. `citewell eval` reports the
  **false-abstain rate** (answerable questions flagged "not in the documents") and the **false-answer
  rate** (unanswerable questions flagged answerable), and `--answerable-threshold` tries other values.

## Calibration (hash embeddings, lexical reranker; 81 answerable, 28 unanswerable questions)

| threshold | false abstain | false answer |
|---:|---:|---:|
| 0.20 | 0.12 | 0.71 |
| 0.30 | 0.19 | 0.43 |
| 0.35 | 0.25 | 0.29 |
| 0.50 | 0.31 | 0.11 |

0.35 sits near the equal-error point. Separation is moderate: paraphrased questions that share few
words with the answer look unanswerable, and unanswerable questions that mention policy vocabulary
look answerable.

## Consequences

- Useful as a hint, not as a gate. Raise the threshold for stricter "say I don't know" behaviour, lower it
  to avoid false abstention; recalibrate with `citewell eval` on your own documents and questions.
- A cross-encoder reranker (`rerank: true`) contributes its probability and should separate better; this
  was not measured here because the calibration environment has no models. A model-aware signal (vector
  similarity, reranker margin) can replace the confidence later without changing the API.
