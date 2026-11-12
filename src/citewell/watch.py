"""Keep a collection in sync with a folder: ``citewell watch``.

Plain polling on file size and modification time: no extra dependency, works the same on Linux,
macOS and Windows, and on network or container mounts where file-system events are unreliable.
A change is only acted on once the file has stopped changing for one full poll, so half-written
files (large copies, editors saving in several steps) are never ingested. Unchanged content is
skipped by the normal content hash, so a touched-but-identical file costs nothing.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from citewell.ingest import IngestService
from citewell.loaders import iter_files
from citewell.store import Store

Signature = tuple[int, int]  # (modification time in ns, size in bytes)
Snapshot = dict[str, tuple[Path, Signature]]


@dataclass(frozen=True, slots=True)
class WatchEvent:
    kind: Literal["ingested", "unchanged", "skipped", "error", "removed"]
    source: str
    detail: str = ""


def take_snapshot(paths: Iterable[Path], recursive: bool = True) -> Snapshot:
    """Supported files under ``paths`` keyed by their collection source name."""
    snap: Snapshot = {}
    for path, source in iter_files(paths, recursive=recursive):
        try:
            st = path.stat()
        except OSError:  # vanished between listing and stat
            continue
        snap[source] = (path, (st.st_mtime_ns, st.st_size))
    return snap


class Watcher:
    """State machine behind the watch loop; ``poll()`` is one pass and is easy to test."""

    def __init__(
        self,
        ingest: IngestService,
        store: Store,
        paths: Sequence[Path],
        collection: str,
        language: str | None = None,
        recursive: bool = True,
        prune: bool = False,
    ):
        self.ingest = ingest
        self.store = store
        self.paths = list(paths)
        self.collection = collection
        self.language = language
        self.recursive = recursive
        self.prune = prune
        self._done: dict[str, Signature] = {}  # what is already in the index
        self._previous: Snapshot = {}

    def poll(self, initial: bool = False) -> list[WatchEvent]:
        current = take_snapshot(self.paths, self.recursive)
        events: list[WatchEvent] = []
        for source, (path, sig) in current.items():
            if self._done.get(source) == sig:
                continue
            stable = initial or self._previous.get(source, (path, None))[1] == sig
            if stable:
                events.append(self._ingest(path, source, sig))
        if self.prune:
            for source in [s for s in self._done if s not in current]:
                if source not in self._previous:  # missing for two polls in a row
                    events.append(self._remove(source))
        self._previous = current
        return events

    def _ingest(self, path: Path, source: str, sig: Signature) -> WatchEvent:
        try:
            result = self.ingest.ingest_bytes(path.read_bytes(), source, self.collection, self.language)
        except Exception as exc:  # keep watching; the file is retried when it changes again
            self._done[source] = sig
            return WatchEvent("error", source, f"{type(exc).__name__}: {exc}")
        self._done[source] = sig
        kind: Literal["ingested", "unchanged", "skipped", "error"] = (
            result.status if result.status in ("ingested", "unchanged", "skipped", "error") else "error"  # type: ignore[assignment]
        )
        detail = result.message or (f"{result.chunks} chunks" if result.chunks else "")
        return WatchEvent(kind, source, detail)

    def _remove(self, source: str) -> WatchEvent:
        self._done.pop(source, None)
        try:
            self.store.delete_document(self.collection, source)
        except Exception as exc:
            return WatchEvent("error", source, f"{type(exc).__name__}: {exc}")
        return WatchEvent("removed", source)


def run_watch(
    watcher: Watcher,
    interval: float = 2.0,
    on_event: Callable[[WatchEvent], None] | None = None,
    max_polls: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Initial sync, then poll every ``interval`` seconds until interrupted (or ``max_polls``)."""
    emit = on_event or (lambda _e: None)
    for event in watcher.poll(initial=True):
        emit(event)
    polls = 0
    while max_polls is None or polls < max_polls:
        sleep(interval)
        polls += 1
        for event in watcher.poll():
            emit(event)
