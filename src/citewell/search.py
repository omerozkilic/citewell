"""Retrieval pipeline: vector / keyword / hybrid (RRF) with optional reranking."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass

from citewell.config import Settings
from citewell.embeddings import Embedder
from citewell.fusion import reciprocal_rank_fusion
from citewell.models import ChunkRecord, Collection, SearchHit, SearchResponse
from citewell.rerank import Reranker
from citewell.store import NotFoundError, Store
from citewell.text import best_quote

log = logging.getLogger(__name__)

MODES = ("vector", "keyword", "hybrid")


@dataclass(slots=True)
class SearchRequest:
    query: str
    top_k: int = 5
    mode: str = "hybrid"
    collections: Sequence[str] | None = None
    rerank: bool | None = None
    source_prefix: str | None = None


class SearchService:
    def __init__(
        self,
        store: Store,
        embedder: Embedder,
        settings: Settings,
        reranker: Reranker | None = None,
    ):
        self.store = store
        self._embedder = embedder
        self._reranker = reranker
        self.settings = settings

    @property
    def embedder(self) -> Embedder:
        return self._embedder

    @property
    def reranker(self) -> Reranker | None:
        return self._reranker

    def _resolve_collections(self, names: Sequence[str] | None) -> list[Collection]:
        available = {c.name: c for c in self.store.list_collections()}
        if not names:
            if self.settings.default_collection in available:
                return [available[self.settings.default_collection]]
            return list(available.values())
        if list(names) == ["*"]:
            return list(available.values())
        missing = [n for n in names if n not in available]
        if missing:
            raise NotFoundError(f"unknown collection(s): {', '.join(missing)}")
        return [available[n] for n in names]

    def search(self, req: SearchRequest) -> SearchResponse:
        query = req.query.strip()
        if not query:
            raise ValueError("query must not be empty")
        if req.mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        top_k = max(1, min(req.top_k, self.settings.max_top_k))
        use_rerank = self.settings.rerank_by_default if req.rerank is None else req.rerank
        if use_rerank and self.reranker is None:
            raise ValueError("reranking requested but no reranker is configured")
        if req.mode in ("vector", "hybrid"):
            _ = self.embedder  # load the model before timing: took_ms measures search only

        t0 = time.perf_counter()

        collections = self._resolve_collections(req.collections)
        if not collections:
            return SearchResponse(
                query=query, mode=req.mode, reranked=False, collections=[], took_ms=0.0, hits=[]
            )
        col_ids = [c.id for c in collections]
        pool = max(
            top_k, self.settings.rerank_candidates if use_rerank else top_k, self.settings.candidate_pool
        )

        rankings: list[list[str]] = []
        per_ret: dict[str, dict[str, float]] = {}

        if req.mode in ("vector", "hybrid"):
            qv = self.embedder.embed_query(query)
            vec_hits = self.store.vector_search(qv, col_ids, pool, req.source_prefix)
            rankings.append([h.chunk_id for h in vec_hits])
            for rank, h in enumerate(vec_hits, start=1):
                per_ret.setdefault(h.chunk_id, {}).update({"vector": h.score, "vector_rank": rank})

        if req.mode in ("keyword", "hybrid"):
            # One ranked list per text-search language, so collections with different
            # stemmers can still be searched together.
            by_lang: dict[str, list[int]] = {}
            for c in collections:
                by_lang.setdefault(c.language, []).append(c.id)
            for lang, ids in by_lang.items():
                kw_hits = self.store.keyword_search(
                    query, lang, ids, pool, req.source_prefix, folded=self.settings.fold_diacritics
                )
                rankings.append([h.chunk_id for h in kw_hits])
                for rank, h in enumerate(kw_hits, start=1):
                    per_ret.setdefault(h.chunk_id, {}).update({"keyword": h.score, "keyword_rank": rank})

        if req.mode == "hybrid":
            fused = reciprocal_rank_fusion(rankings, k=self.settings.rrf_k)
            for cid, s in fused:
                per_ret[cid]["rrf"] = s
            ordered = [(cid, s) for cid, s in fused]
        else:
            key = "vector" if req.mode == "vector" else "keyword"
            merged = sorted({cid for r in rankings for cid in r}, key=lambda cid: -per_ret[cid].get(key, 0.0))
            ordered = [(cid, per_ret[cid].get(key, 0.0)) for cid in merged]

        # Fetch a few extra candidates so near-duplicates can be dropped without losing top_k.
        candidates = ordered[: (pool if use_rerank else min(len(ordered), top_k * 3))]
        records = self.store.get_chunks([cid for cid, _ in candidates])
        candidates = [(cid, s) for cid, s in candidates if cid in records]

        if use_rerank and candidates:
            assert self.reranker is not None
            texts = [
                _rerank_text(records[cid].title, records[cid].section, records[cid].text)
                for cid, _ in candidates
            ]
            rr = self.reranker.score(query, texts)
            for (cid, _), s in zip(candidates, rr, strict=True):
                per_ret[cid]["rerank"] = s
            candidates = sorted(
                ((cid, per_ret[cid]["rerank"]) for cid, _ in candidates), key=lambda kv: -kv[1]
            )

        lang_of = {c.name: c.language for c in collections}
        hits: list[SearchHit] = []
        candidates = select_diverse(candidates, records, top_k)
        for rank, (cid, score) in enumerate(candidates, start=1):
            rec = records[cid]
            hits.append(
                SearchHit(
                    rank=rank,
                    score=round(float(score), 6),
                    chunk_id=cid,
                    collection=rec.collection,
                    document_id=rec.document_id,
                    source=rec.source,
                    title=rec.title,
                    page=rec.page,
                    page_label=rec.page_label,
                    section=rec.section,
                    text=rec.text,
                    quote=best_quote(
                        rec.text, query, lang_of.get(rec.collection, "turkish"), self.settings.quote_max_chars
                    ),
                    scores={k: round(float(v), 6) for k, v in per_ret.get(cid, {}).items()},
                )
            )
        took = (time.perf_counter() - t0) * 1000
        log.debug("search mode=%s k=%s took=%.1fms", req.mode, top_k, took)
        return SearchResponse(
            query=query,
            mode=req.mode,
            reranked=bool(use_rerank),
            collections=[c.name for c in collections],
            took_ms=round(took, 2),
            hits=hits,
        )


def _rerank_text(title: str | None, section: str | None, text: str) -> str:
    head = " — ".join(x for x in (title, section) if x)
    return f"{head}\n{text}" if head else text


def overlaps(a: ChunkRecord, b: ChunkRecord, threshold: float = 0.5) -> bool:
    """True if two chunks share at least ``threshold`` of the shorter one's text.

    Overlapping chunks from the same page (or Markdown section) carry the same
    passage twice; showing both wastes a slot in the top-k.
    """
    if (a.document_id, a.page, a.section) != (b.document_id, b.page, b.section):
        return False
    inter = min(a.char_end, b.char_end) - max(a.char_start, b.char_start)
    if inter <= 0:
        return False
    shorter = min(a.char_end - a.char_start, b.char_end - b.char_start)
    return inter >= threshold * max(1, shorter)


def select_diverse(
    ranked: Sequence[tuple[str, float]], records: dict[str, ChunkRecord], k: int
) -> list[tuple[str, float]]:
    """Keep the ranking order but skip chunks that mostly repeat a higher-ranked one."""
    kept: list[tuple[str, float]] = []
    for cid, score in ranked:
        rec = records[cid]
        if any(overlaps(rec, records[other]) for other, _ in kept):
            continue
        kept.append((cid, score))
        if len(kept) == k:
            break
    return kept
