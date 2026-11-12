"""Install diagnostics behind ``citewell doctor``.

Read-only: nothing is created, migrated or downloaded, and no models are loaded, so it is
safe to run against a production database and works without network access.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from typing import Literal

import psycopg

from citewell import __version__, db
from citewell.config import Settings
from citewell.hub import is_model_cached, offline_requested

Status = Literal["ok", "warn", "fail"]


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str = ""
    hint: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _loopback(host: str) -> bool:
    return host in ("127.0.0.1", "localhost", "::1")


def check_database(s: Settings) -> list[Check]:
    checks: list[Check] = []
    target = db.describe_url(s.database_url)
    try:
        conn = psycopg.connect(s.database_url, connect_timeout=5)
    except psycopg.Error as exc:
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        return [
            Check(
                "database",
                "fail",
                f"cannot connect to {target} ({reason})",
                "Start it with `docker compose up -d db`, or set CITEWELL_DATABASE_URL.",
            )
        ]
    with conn:
        server = conn.execute("SHOW server_version").fetchone()
        checks.append(Check("postgresql", "ok", f"{server[0] if server else '?'} at {target}"))

        version = db.pgvector_version(conn)
        if version is None:
            checks.append(
                Check(
                    "pgvector",
                    "fail",
                    "extension not installed",
                    "Use a pgvector image (e.g. pgvector/pgvector) and run `citewell init`.",
                )
            )
        else:
            text = ".".join(map(str, version))
            if version >= (0, 8):
                checks.append(Check("pgvector", "ok", text))
            else:
                checks.append(
                    Check(
                        "pgvector",
                        "warn",
                        f"{text} (0.8 or newer recommended)",
                        "Upgrade the pgvector extension.",
                    )
                )

        meta_table = conn.execute("SELECT to_regclass('citewell_meta') IS NOT NULL").fetchone()
        if not (meta_table and meta_table[0]):
            checks.append(Check("schema", "fail", "database is not initialised", "Run `citewell init`."))
            return checks

        meta = {str(k): str(v) for k, v in conn.execute("SELECT key, value FROM citewell_meta").fetchall()}
        model_id = f"hash-{s.embedding_dim}" if s.embedding_backend == "hash" else s.embedding_model
        try:
            db.check_meta(meta, s.embedding_dim, model_id)
            checks.append(
                Check("embedding dimension", "ok", f"{model_id} ({s.embedding_dim}-d) matches the database")
            )
        except db.SchemaMismatchError as exc:
            checks.append(
                Check(
                    "embedding dimension",
                    "fail",
                    str(exc),
                    "Restore the original CITEWELL_EMBEDDING_MODEL/_DIM or re-ingest into a fresh database.",
                )
            )
        pending = db.pending_migrations(conn)
        if pending:
            checks.append(
                Check(
                    "migrations",
                    "warn",
                    f"{len(pending)} pending ({', '.join(pending)})",
                    "Run `citewell init` to apply them.",
                )
            )
        else:
            checks.append(Check("migrations", "ok", "all applied"))
    return checks


def check_models(s: Settings) -> list[Check]:
    checks: list[Check] = []
    needed: list[str] = []
    if s.embedding_backend == "hash":
        checks.append(
            Check(
                "embeddings",
                "warn",
                "hash backend: for tests and demos, not semantic",
                "Use sentence-transformers.",
            )
        )
    else:
        try:
            import sentence_transformers  # noqa: F401
        except ImportError:
            checks.append(
                Check(
                    "embeddings",
                    "fail",
                    "sentence-transformers is not installed",
                    "Install it with `pip install 'citewell[models]'`.",
                )
            )
        else:
            needed.append(s.embedding_model)
            checks.append(_model_check("embeddings", s.embedding_model))
    if s.reranker_backend == "sentence-transformers":
        needed.append(s.reranker_model)
        checks.append(_model_check("reranker", s.reranker_model))
    else:
        checks.append(
            Check("reranker", "ok" if s.reranker_backend == "lexical" else "warn", s.reranker_backend)
        )

    if needed and all(is_model_cached(m) for m in needed):
        state = "HF_HUB_OFFLINE is set" if offline_requested() else "all models cached"
        checks.append(Check("offline", "ok", f"ready to run without network ({state})"))
    elif needed:
        missing = [m for m in needed if not is_model_cached(m)]
        checks.append(
            Check(
                "offline",
                "fail" if offline_requested() else "warn",
                f"not cached: {', '.join(missing)}",
                "Run `citewell models download` once with internet access.",
            )
        )
    return checks


def _model_check(name: str, model: str) -> Check:
    if is_model_cached(model):
        return Check(name, "ok", f"{model} (cached)")
    return Check(name, "warn", f"{model} (not cached yet)", "Run `citewell models download`.")


def check_server(s: Settings) -> list[Check]:
    if s.api_token:
        return [Check("api token", "ok", "set")]
    if _loopback(s.host):
        return [Check("api token", "ok", "not set (fine while bound to localhost)")]
    return [
        Check(
            "api token",
            "warn",
            f"server binds to {s.host} without CITEWELL_API_TOKEN",
            "Set CITEWELL_API_TOKEN and put the server behind TLS.",
        )
    ]


def run_checks(s: Settings) -> list[Check]:
    checks = [
        Check("citewell", "ok", __version__),
        Check("python", "ok", sys.version.split()[0]),
    ]
    checks += check_database(s)
    checks += check_models(s)
    checks += check_server(s)
    return checks


def has_failures(checks: list[Check]) -> bool:
    return any(c.status == "fail" for c in checks)


__all__ = ["Check", "has_failures", "run_checks"]
