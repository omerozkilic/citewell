"""Retrieval evaluation: Recall@k, MRR, page hit rate and latency.

Dataset format (JSON Lines, one query per line)::

    {"id": "q01", "query": "Yıllık izin kaç gün?",
     "relevant": [{"source": "ik-el-kitabi.pdf", "page": 3}],
     "collection": "default"}

A *relevant item* is a ``(source, page)`` pair; ``page`` may be omitted to mark
a whole document (or an unpaged format) as relevant.

Metrics (``k`` = cut-off):

* **Recall@k** – fraction of relevant items found in the top k (document match,
  and page match when the item has a page). Averaged over queries.
* **MRR@k** – mean of ``1 / rank`` of the first relevant hit (0 if none in top k).
* **Hit@k** – fraction of queries with at least one relevant hit in the top k.
* **Page hit@k** – among queries whose relevant items carry pages, fraction whose
  top k contains a hit on the exact page.
* **Doc hit@k** – like Hit@k but ignores page numbers.
* **Latency** – p50 / p95 / mean of end-to-end search time in milliseconds.
"""

from __future__ import annotations

import json
import statistics
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from citewell.models import SearchHit
from citewell.search import SearchRequest, SearchService


class RelevantItem(BaseModel):
    source: str
    page: int | None = None


class EvalQuery(BaseModel):
    id: str
    query: str
    relevant: list[RelevantItem] = Field(min_length=1)
    collection: str | None = None
    tags: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RunConfig:
    mode: str
    rerank: bool = False

    @property
    def label(self) -> str:
        return f"{self.mode}+rerank" if self.rerank else self.mode

    @classmethod
    def parse(cls, spec: str) -> RunConfig:
        mode, _, extra = spec.strip().partition("+")
        if extra and extra != "rerank":
            raise ValueError(f"invalid run spec: {spec!r} (expected e.g. 'hybrid' or 'hybrid+rerank')")
        return cls(mode=mode, rerank=extra == "rerank")


@dataclass(slots=True)
class QueryResult:
    id: str
    query: str
    first_relevant_rank: int | None
    recall: float
    doc_hit: bool
    page_hit: bool | None
    latency_ms: float
    top: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class RunReport:
    label: str
    k: int
    n: int
    recall_at_k: float
    mrr_at_k: float
    hit_at_k: float
    doc_hit_at_k: float
    page_hit_at_k: float | None
    latency_p50_ms: float
    latency_p95_ms: float
    latency_mean_ms: float
    queries: list[QueryResult]

    def summary(self) -> dict[str, object]:
        return {
            "run": self.label,
            "k": self.k,
            "queries": self.n,
            "recall@k": round(self.recall_at_k, 4),
            "mrr@k": round(self.mrr_at_k, 4),
            "hit@k": round(self.hit_at_k, 4),
            "doc_hit@k": round(self.doc_hit_at_k, 4),
            "page_hit@k": None if self.page_hit_at_k is None else round(self.page_hit_at_k, 4),
            "latency_p50_ms": round(self.latency_p50_ms, 1),
            "latency_p95_ms": round(self.latency_p95_ms, 1),
            "latency_mean_ms": round(self.latency_mean_ms, 1),
        }


def load_dataset(path: Path) -> list[EvalQuery]:
    queries: list[EvalQuery] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                queries.append(EvalQuery.model_validate(json.loads(line)))
            except Exception as exc:
                raise ValueError(f"{path}:{lineno}: {exc}") from exc
    if not queries:
        raise ValueError(f"{path}: dataset is empty")
    return queries


def _matches(hit: SearchHit, item: RelevantItem, use_page: bool = True) -> bool:
    if hit.source != item.source:
        return False
    return not (use_page and item.page is not None and hit.page != item.page)


def score_query(
    q: EvalQuery, hits: Sequence[SearchHit], k: int
) -> tuple[int | None, float, bool, bool | None]:
    top = list(hits)[:k]
    first: int | None = None
    for h in top:
        if any(_matches(h, it) for it in q.relevant):
            first = h.rank if first is None else min(first, h.rank)
            break
    found = sum(1 for it in q.relevant if any(_matches(h, it) for h in top))
    recall = found / len(q.relevant)
    doc_hit = any(_matches(h, it, use_page=False) for h in top for it in q.relevant)
    paged = [it for it in q.relevant if it.page is not None]
    page_hit = any(_matches(h, it) for h in top for it in paged) if paged else None
    return first, recall, doc_hit, page_hit


def percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = (len(ordered) - 1) * pct / 100
    lo, hi = int(idx), min(int(idx) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)


def run_eval(
    service: SearchService,
    dataset: Iterable[EvalQuery],
    run: RunConfig,
    k: int = 5,
    default_collection: str | None = None,
    warmup: bool = True,
) -> RunReport:
    queries = list(dataset)
    if warmup and queries:
        # Load models / warm caches so the first query doesn't skew latency.
        head = queries[0]
        service.search(
            SearchRequest(
                query=head.query,
                top_k=k,
                mode=run.mode,
                rerank=run.rerank,
                collections=[c for c in [head.collection or default_collection] if c] or None,
            )
        )

    results: list[QueryResult] = []
    for q in queries:
        col = q.collection or default_collection
        t0 = time.perf_counter()
        resp = service.search(
            SearchRequest(
                query=q.query, top_k=k, mode=run.mode, rerank=run.rerank, collections=[col] if col else None
            )
        )
        latency = (time.perf_counter() - t0) * 1000
        first, recall, doc_hit, page_hit = score_query(q, resp.hits, k)
        results.append(
            QueryResult(
                id=q.id,
                query=q.query,
                first_relevant_rank=first,
                recall=recall,
                doc_hit=doc_hit,
                page_hit=page_hit,
                latency_ms=latency,
                top=[
                    {"rank": h.rank, "source": h.source, "page": h.page, "score": h.score} for h in resp.hits
                ],
            )
        )

    n = len(results)
    lat = [r.latency_ms for r in results]
    paged = [r.page_hit for r in results if r.page_hit is not None]
    return RunReport(
        label=run.label,
        k=k,
        n=n,
        recall_at_k=statistics.fmean(r.recall for r in results) if n else 0.0,
        mrr_at_k=statistics.fmean(
            1 / r.first_relevant_rank if r.first_relevant_rank else 0.0 for r in results
        )
        if n
        else 0.0,
        hit_at_k=sum(r.first_relevant_rank is not None for r in results) / n if n else 0.0,
        doc_hit_at_k=sum(r.doc_hit for r in results) / n if n else 0.0,
        page_hit_at_k=(sum(paged) / len(paged)) if paged else None,
        latency_p50_ms=percentile(lat, 50),
        latency_p95_ms=percentile(lat, 95),
        latency_mean_ms=statistics.fmean(lat) if lat else 0.0,
        queries=results,
    )


def report_markdown(reports: Sequence[RunReport]) -> str:
    """Render a Markdown table suitable for the README / docs."""
    if not reports:
        return ""
    k = reports[0].k
    lines = [
        f"| Run | Recall@{k} | MRR@{k} | Hit@{k} | Page hit@{k} | p50 ms | p95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in reports:
        page = "–" if r.page_hit_at_k is None else f"{r.page_hit_at_k:.3f}"
        lines.append(
            f"| {r.label} | {r.recall_at_k:.3f} | {r.mrr_at_k:.3f} | {r.hit_at_k:.3f} | {page} | "
            f"{r.latency_p50_ms:.0f} | {r.latency_p95_ms:.0f} |"
        )
    return "\n".join(lines)
