"""Reciprocal Rank Fusion (Cormack, Clarke & Büttcher, SIGIR 2009)."""

from __future__ import annotations

from collections.abc import Hashable, Sequence
from typing import TypeVar

K = TypeVar("K", bound=Hashable)


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[K]], k: int = 60, weights: Sequence[float] | None = None
) -> list[tuple[K, float]]:
    """Fuse several ranked lists of ids.

    ``score(d) = Σ_i w_i / (k + rank_i(d))`` with 1-based ranks. Items missing
    from a list simply get no contribution from it. Ties are broken by the best
    individual rank, then by first appearance, so the output is deterministic.
    """
    if weights is None:
        weights = [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError("weights and rankings must have the same length")

    scores: dict[K, float] = {}
    best_rank: dict[K, int] = {}
    first_seen: dict[K, int] = {}
    counter = 0
    for ranking, w in zip(rankings, weights, strict=True):
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + w / (k + rank)
            best_rank[item] = min(best_rank.get(item, rank), rank)
            if item not in first_seen:
                first_seen[item] = counter
                counter += 1
    return sorted(scores.items(), key=lambda kv: (-kv[1], best_rank[kv[0]], first_seen[kv[0]]))
