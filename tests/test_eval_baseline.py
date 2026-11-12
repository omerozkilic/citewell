"""Baseline comparison for ``citewell eval`` (no database needed)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from citewell.evaluation import (
    RunReport,
    baseline_payload,
    compare_to_baseline,
    comparison_markdown,
    load_baseline,
)


def _report(
    label: str = "hybrid", recall: float = 0.9, mrr: float = 0.8, page: float | None = 1.0
) -> RunReport:
    return RunReport(
        label=label,
        k=5,
        n=10,
        recall_at_k=recall,
        mrr_at_k=mrr,
        hit_at_k=recall,
        doc_hit_at_k=recall,
        page_hit_at_k=page,
        latency_p50_ms=3.0,
        latency_p95_ms=4.0,
        latency_mean_ms=3.2,
        queries=[],
    )


def test_payload_keeps_quality_metrics_only() -> None:
    payload = baseline_payload([_report(), _report("keyword", page=None)])
    assert payload["k"] == 5
    runs = payload["runs"]
    assert runs["hybrid"] == {"recall@k": 0.9, "mrr@k": 0.8, "page_hit@k": 1.0}  # type: ignore[index]
    assert "page_hit@k" not in runs["keyword"]  # type: ignore[index]
    assert "latency" not in json.dumps(payload)


def test_same_results_do_not_regress() -> None:
    reports = [_report()]
    deltas = compare_to_baseline(reports, baseline_payload(reports))
    assert deltas and not any(d.regressed for d in deltas)


def test_drop_within_tolerance_is_allowed_but_beyond_is_a_regression() -> None:
    base = baseline_payload([_report(recall=0.90)])
    assert not any(d.regressed for d in compare_to_baseline([_report(recall=0.885)], base, tolerance=0.02))
    regressed = [d for d in compare_to_baseline([_report(recall=0.85)], base, tolerance=0.02) if d.regressed]
    assert [(d.run, d.metric) for d in regressed] == [("hybrid", "recall@k")]
    assert regressed[0].delta == pytest.approx(-0.05)


def test_improvement_and_new_runs_are_fine() -> None:
    base = baseline_payload([_report()])
    deltas = compare_to_baseline([_report(recall=0.95), _report("vector")], base)
    assert not any(d.regressed for d in deltas)
    assert {d.run for d in deltas} == {"hybrid"}  # "vector" is not in the baseline yet


def test_different_k_is_rejected() -> None:
    base = baseline_payload([_report()])
    base["k"] = 10
    with pytest.raises(ValueError, match="k=10"):
        compare_to_baseline([_report()], base)


def test_load_baseline_validates(tmp_path: Path) -> None:
    good = tmp_path / "b.json"
    good.write_text(json.dumps(baseline_payload([_report()])))
    assert load_baseline(good)["k"] == 5
    for name, content in (
        ("missing.json", None),
        ("bad.json", "{"),
        ("wrong.json", "[]"),
        ("noruns.json", "{}"),
    ):
        path = tmp_path / name
        if content is not None:
            path.write_text(content)
        with pytest.raises(ValueError):
            load_baseline(path)


def test_markdown_flags_regressions() -> None:
    base = baseline_payload([_report(recall=0.95)])
    text = comparison_markdown(compare_to_baseline([_report(recall=0.80)], base), 0.02)
    assert "❌ regression" in text and "hybrid" in text
    assert "No runs matched" in comparison_markdown([], 0.02)
