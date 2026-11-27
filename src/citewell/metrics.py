"""Minimal Prometheus metrics (text exposition format 0.0.4) without any extra dependency.

Only used when ``CITEWELL_METRICS`` is on. Counters and histograms live in memory per process.
"""

import threading
from collections.abc import Iterable, Sequence

Labels = tuple[tuple[str, str], ...]

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(pairs: Iterable[tuple[str, str]]) -> str:
    items = ",".join(f'{k}="{_escape(v)}"' for k, v in pairs)
    return "{" + items + "}" if items else ""


def _key(labels: dict[str, str]) -> Labels:
    return tuple(sorted(labels.items()))


def _number(value: float) -> str:
    return repr(int(value)) if float(value).is_integer() else repr(round(value, 9))


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._help: dict[str, tuple[str, str]] = {}
        self._counters: dict[str, dict[Labels, float]] = {}
        self._histograms: dict[str, dict[Labels, tuple[list[int], float, int]]] = {}

    def counter(self, name: str, help_: str, **labels: str) -> None:
        with self._lock:
            self._help.setdefault(name, (help_, "counter"))
            series = self._counters.setdefault(name, {})
            key = _key(labels)
            series[key] = series.get(key, 0.0) + 1.0

    def observe(self, name: str, help_: str, value: float, **labels: str) -> None:
        with self._lock:
            self._help.setdefault(name, (help_, "histogram"))
            series = self._histograms.setdefault(name, {})
            key = _key(labels)
            counts, total, n = series.get(key) or ([0] * len(LATENCY_BUCKETS), 0.0, 0)
            for i, bound in enumerate(LATENCY_BUCKETS):
                if value <= bound:
                    counts[i] += 1
            series[key] = (counts, total + value, n + 1)

    def render(self, gauges: Sequence[tuple[str, str, Labels, float]] = ()) -> str:
        """Exposition text. ``gauges`` are ``(name, help, labels, value)`` sampled at scrape time."""
        lines: list[str] = []
        with self._lock:
            for name, series in sorted(self._counters.items()):
                lines += [f"# HELP {name} {self._help[name][0]}", f"# TYPE {name} counter"]
                lines += [f"{name}{_labels(k)} {_number(v)}" for k, v in sorted(series.items())]
            for name, hseries in sorted(self._histograms.items()):
                lines += [f"# HELP {name} {self._help[name][0]}", f"# TYPE {name} histogram"]
                for key, (counts, total, n) in sorted(hseries.items()):
                    for bound, c in zip(LATENCY_BUCKETS, counts, strict=True):
                        lines.append(f"{name}_bucket{_labels([*key, ('le', _number(bound))])} {c}")
                    lines.append(f"{name}_bucket{_labels([*key, ('le', '+Inf')])} {n}")
                    lines.append(f"{name}_sum{_labels(key)} {_number(total)}")
                    lines.append(f"{name}_count{_labels(key)} {n}")
        seen: set[str] = set()
        for name, help_, labels, value in gauges:
            if name not in seen:
                lines += [f"# HELP {name} {help_}", f"# TYPE {name} gauge"]
                seen.add(name)
            lines.append(f"{name}{_labels(labels)} {_number(value)}")
        return "\n".join(lines) + "\n"
