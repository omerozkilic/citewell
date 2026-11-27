from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from citewell.audit import AuditLog


def test_disabled_log_does_nothing() -> None:
    log = AuditLog(None)
    assert not log.enabled
    log.record("t", "GET", "/x", 200, "1.2.3.4")  # must not raise


def test_entries_are_json_lines_and_private(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    assert log.enabled
    log.record("team-a", "POST", "/v1/search", 200, "10.0.0.7")
    log.record(None, "GET", "/v1/collections", 401, None)
    first, second = (json.loads(line) for line in path.read_text(encoding="utf-8").splitlines())
    assert first["token"] == "team-a" and first["client"] == "10.0.0.7"
    assert (first["method"], first["path"], first["status"]) == ("POST", "/v1/search", 200)
    assert first["ts"].endswith("+00:00")
    assert second["token"] is None and second["status"] == 401
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_unwritable_log_is_reported_not_raised(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    log = AuditLog(tmp_path)  # a directory cannot be opened for appending
    with caplog.at_level("WARNING", logger="citewell.audit"):
        log.record("t", "GET", "/x", 200, None)
    assert "cannot write audit log" in caplog.text
