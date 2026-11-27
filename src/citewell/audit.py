"""Optional audit log of HTTP requests: who (token name), what (method, path) and the outcome.

One JSON object per line, appended to ``CITEWELL_AUDIT_LOG``. Query strings and request bodies are
never recorded, so search queries and document text do not end up in the log.
"""

import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)


class AuditLog:
    def __init__(self, path: Path | None):
        self.path = path
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.path is not None

    def record(self, token: str | None, method: str, path: str, status: int, client: str | None) -> None:
        """Append one entry. A failing log must never break the request, so errors are only logged."""
        if self.path is None:
            return
        entry = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "token": token,
            "client": client,
            "method": method,
            "path": path,
            "status": status,
        }
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        try:
            with self._lock:
                fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as fh:
                    fh.write(line)
        except OSError as exc:
            log.warning("cannot write audit log %s: %s", self.path, exc)
