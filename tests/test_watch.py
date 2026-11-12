"""``citewell watch`` change detection (no database: the index is faked)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from citewell.models import IngestResult
from citewell.watch import Watcher, WatchEvent, run_watch, take_snapshot


class FakeIngest:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes]] = []
        self.fail_for: set[str] = set()

    def ingest_bytes(
        self, data: bytes, source: str, collection: str | None = None, language: str | None = None, **_: Any
    ) -> IngestResult:
        if source in self.fail_for:
            raise ValueError("boom")
        self.calls.append((source, data))
        return IngestResult(source=source, status="ingested", chunks=2)


class FakeStore:
    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    def delete_document(self, collection: str, source: str) -> bool:
        self.deleted.append((collection, source))
        return True


def _write(path: Path, text: str, mtime: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(mtime * 10**9, mtime * 10**9))


def _watcher(root: Path, prune: bool = False) -> tuple[Watcher, FakeIngest, FakeStore]:
    ingest, store = FakeIngest(), FakeStore()
    return Watcher(ingest, store, [root], "docs", prune=prune), ingest, store  # type: ignore[arg-type]


def test_snapshot_lists_supported_visible_files(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "a", 1)
    _write(tmp_path / "sub" / "b.txt", "b", 1)
    _write(tmp_path / "image.png", "x", 1)
    _write(tmp_path / ".hidden" / "c.md", "c", 1)
    assert sorted(take_snapshot([tmp_path])) == ["a.md", "sub/b.txt"]


def test_initial_poll_ingests_everything_immediately(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "hello", 1)
    w, ingest, _ = _watcher(tmp_path)
    events = w.poll(initial=True)
    assert [(e.kind, e.source) for e in events] == [("ingested", "a.md")]
    assert w.poll() == []  # nothing changed
    assert len(ingest.calls) == 1


def test_new_file_waits_one_poll_so_half_written_files_are_skipped(tmp_path: Path) -> None:
    w, ingest, _ = _watcher(tmp_path)
    w.poll(initial=True)
    _write(tmp_path / "new.md", "part", 10)
    assert w.poll() == []  # first sighting: wait
    _write(tmp_path / "new.md", "part and more", 11)  # still being written
    assert w.poll() == []
    events = w.poll()  # unchanged since the last poll: ingest
    assert [e.source for e in events] == ["new.md"]
    assert ingest.calls == [("new.md", b"part and more")]


def test_modified_file_is_reingested(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "v1", 1)
    w, ingest, _ = _watcher(tmp_path)
    w.poll(initial=True)
    _write(tmp_path / "a.md", "version two", 5)
    w.poll()
    events = w.poll()
    assert [e.kind for e in events] == ["ingested"]
    assert ingest.calls[-1] == ("a.md", b"version two")


def test_deleted_files_are_kept_unless_prune(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "x", 1)
    w, _, store = _watcher(tmp_path, prune=False)
    w.poll(initial=True)
    (tmp_path / "a.md").unlink()
    assert w.poll() == [] and w.poll() == []
    assert store.deleted == []


def test_prune_removes_after_two_polls_and_survives_a_transient_rename(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "x", 1)
    w, _, store = _watcher(tmp_path, prune=True)
    w.poll(initial=True)
    # Editors often save by replacing the file: gone for one poll, back for the next.
    (tmp_path / "a.md").rename(tmp_path / "a.md.tmp")
    assert w.poll() == []
    (tmp_path / "a.md.tmp").rename(tmp_path / "a.md")
    assert w.poll() == [] and store.deleted == []
    (tmp_path / "a.md").unlink()
    assert w.poll() == []
    events = w.poll()
    assert [(e.kind, e.source) for e in events] == [("removed", "a.md")]
    assert store.deleted == [("docs", "a.md")]


def test_errors_are_reported_and_not_retried_until_the_file_changes(tmp_path: Path) -> None:
    _write(tmp_path / "bad.md", "x", 1)
    w, ingest, _ = _watcher(tmp_path)
    ingest.fail_for.add("bad.md")
    events = w.poll(initial=True)
    assert events[0].kind == "error" and "boom" in events[0].detail
    assert w.poll() == [] and w.poll() == []
    ingest.fail_for.clear()
    _write(tmp_path / "bad.md", "fixed", 9)
    w.poll()
    assert [e.kind for e in w.poll()] == ["ingested"]


def test_run_watch_polls_with_the_given_interval(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "x", 1)
    w, _, _ = _watcher(tmp_path)
    sleeps: list[float] = []
    seen: list[WatchEvent] = []
    run_watch(w, interval=0.5, on_event=seen.append, max_polls=3, sleep=sleeps.append)
    assert sleeps == [0.5, 0.5, 0.5]
    assert [e.source for e in seen] == ["a.md"]


def test_unsupported_directory_is_an_error(tmp_path: Path) -> None:
    w, _, _ = _watcher(tmp_path / "missing")
    with pytest.raises(FileNotFoundError):
        w.poll(initial=True)


def test_failed_removal_is_reported_as_an_error(tmp_path: Path) -> None:
    _write(tmp_path / "a.md", "x", 1)
    w, _, store = _watcher(tmp_path, prune=True)
    w.poll(initial=True)

    def broken(collection: str, source: str) -> bool:
        raise RuntimeError("db down")

    store.delete_document = broken  # type: ignore[method-assign]
    (tmp_path / "a.md").unlink()
    w.poll()
    events = w.poll()
    assert [(e.kind, e.source) for e in events] == [("error", "a.md")]
    assert "db down" in events[0].detail


def test_file_vanishing_between_listing_and_stat_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "citewell.watch.iter_files", lambda paths, recursive=True: [(tmp_path / "gone.md", "gone.md")]
    )
    assert take_snapshot([tmp_path]) == {}


def test_run_watch_reports_files_that_appear_later(tmp_path: Path) -> None:
    w, _, _ = _watcher(tmp_path)
    seen: list[WatchEvent] = []
    calls = 0

    def sleep(_: float) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            _write(tmp_path / "late.md", "hello", 20)

    run_watch(w, interval=0.1, on_event=seen.append, max_polls=3, sleep=sleep)
    assert [e.source for e in seen] == ["late.md"]
