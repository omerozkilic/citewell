"""Prometheus text exposition (no database)."""

from __future__ import annotations

import pytest

from citewell.metrics import LATENCY_BUCKETS, Metrics


def test_counter_rendering_with_labels_and_escaping() -> None:
    m = Metrics()
    m.counter("req_total", "Requests.", route="/a", status="200")
    m.counter("req_total", "Requests.", route="/a", status="200")
    m.counter("req_total", "Requests.", route='/"b"\\\n', status="404")
    lines = m.render().splitlines()
    assert lines[:2] == ["# HELP req_total Requests.", "# TYPE req_total counter"]
    assert 'req_total{route="/a",status="200"} 2' in lines
    assert 'req_total{route="/\\"b\\"\\\\\\n",status="404"} 1' in lines


def test_histogram_buckets_are_cumulative() -> None:
    m = Metrics()
    for value in (0.003, 0.03, 0.03, 20.0):
        m.observe("dur_seconds", "Duration.", value, mode="hybrid")
    text = m.render()
    assert "# TYPE dur_seconds histogram" in text
    assert 'dur_seconds_bucket{mode="hybrid",le="0.005"} 1' in text
    assert 'dur_seconds_bucket{mode="hybrid",le="0.05"} 3' in text
    assert 'dur_seconds_bucket{mode="hybrid",le="10"} 3' in text
    assert 'dur_seconds_bucket{mode="hybrid",le="+Inf"} 4' in text
    assert 'dur_seconds_count{mode="hybrid"} 4' in text
    assert 'dur_seconds_sum{mode="hybrid"} 20.063' in text
    buckets = [int(line.rsplit(" ", 1)[1]) for line in text.splitlines() if "_bucket" in line]
    assert buckets == sorted(buckets) and len(buckets) == len(LATENCY_BUCKETS) + 1


def test_gauges_are_sampled_at_render_time() -> None:
    m = Metrics()
    text = m.render(
        [
            ("docs", "Documents.", (("collection", "a"),), 3),
            ("docs", "Documents.", (("collection", "b"),), 0),
            ("info", "Build.", (("version", "1.0"),), 1.0),
        ]
    )
    assert text.count("# TYPE docs gauge") == 1 and 'docs{collection="a"} 3' in text
    assert 'docs{collection="b"} 0' in text and 'info{version="1.0"} 1' in text
    assert Metrics().render() == "\n"


def test_fractional_values_keep_precision() -> None:
    m = Metrics()
    m.observe("x_seconds", "x", 0.1234567891234, a="b")
    assert 'x_seconds_sum{a="b"} 0.123456789' in m.render()
    with pytest.raises(TypeError):
        m.counter("c", "c", 5)  # type: ignore[call-arg, misc]
