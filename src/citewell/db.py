"""Connection pool and a tiny, dependency-free migration runner."""

from __future__ import annotations

import logging
from importlib import resources

import psycopg
import psycopg.conninfo
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

log = logging.getLogger(__name__)

MIGRATIONS_PACKAGE = "citewell.migrations"


class SchemaMismatchError(RuntimeError):
    pass


class DatabaseUnavailableError(RuntimeError):
    pass


def describe_url(url: str) -> str:
    """``host:port/dbname`` without credentials, for error messages."""
    try:
        info = psycopg.conninfo.conninfo_to_dict(url)
    except psycopg.ProgrammingError:
        return "<invalid database URL>"
    host = info.get("host") or "localhost"
    return f"{host}:{info.get('port') or 5432}/{info.get('dbname') or ''}"


def check_connection(url: str, timeout: int = 5) -> None:
    """Fail fast with an actionable message instead of a 30 s pool retry loop."""
    try:
        with psycopg.connect(url, connect_timeout=timeout):
            pass
    except psycopg.OperationalError as exc:
        lines = [ln.strip() for ln in str(exc).splitlines() if ln.strip()] or [type(exc).__name__]
        reason = next((ln.rsplit("failed: ", 1)[-1] for ln in lines if "failed: " in ln), lines[-1])
        raise DatabaseUnavailableError(
            f"cannot connect to PostgreSQL at {describe_url(url)} ({reason}).\n"
            "Is the database running? With Docker: `docker compose up -d db` "
            "(check with `docker compose ps`). Otherwise set CITEWELL_DATABASE_URL."
        ) from exc


def _configure(conn: psycopg.Connection) -> None:
    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        # Extension not created yet (fresh database before `citewell init`).
        log.debug("pgvector type not registered on this connection yet")
    conn.commit()


def create_pool(url: str, min_size: int = 1, max_size: int = 8) -> ConnectionPool:
    check_connection(url)
    pool = ConnectionPool(
        url,
        min_size=min_size,
        max_size=max_size,
        configure=_configure,
        open=False,
        kwargs={"autocommit": False},
    )
    pool.open(wait=True, timeout=30)
    return pool


def _migration_files() -> list[tuple[int, str, str]]:
    out = []
    for entry in resources.files(MIGRATIONS_PACKAGE).iterdir():
        name = entry.name
        if name.endswith(".sql") and name[:4].isdigit():
            out.append((int(name[:4]), name, entry.read_text(encoding="utf-8")))
    return sorted(out)


def migrate(conn: psycopg.Connection, embedding_dim: int, embedding_model: str) -> list[str]:
    """Apply pending migrations; returns the names of applied files.

    The embedding dimension and model are recorded in ``citewell_meta`` the first
    time and verified afterwards, because a pgvector column has a fixed width and
    vectors from different models are not comparable.
    """
    applied: list[str] = []
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('citewell_migrate'))")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS citewell_migrations ("
            " version int PRIMARY KEY, name text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {row[0] for row in conn.execute("SELECT version FROM citewell_migrations").fetchall()}
        for version, name, sql in _migration_files():
            if version in done:
                continue
            log.info("applying migration %s", name)
            conn.execute(sql.format(dim=int(embedding_dim)).encode())
            conn.execute("INSERT INTO citewell_migrations (version, name) VALUES (%s, %s)", (version, name))
            applied.append(name)

        meta: dict[str, str] = {
            str(k): str(v) for k, v in conn.execute("SELECT key, value FROM citewell_meta").fetchall()
        }
        if not meta:
            conn.execute(
                "INSERT INTO citewell_meta (key, value) "
                "VALUES ('embedding_dim', %s), ('embedding_model', %s)",
                (str(embedding_dim), embedding_model),
            )
        else:
            check_meta(meta, embedding_dim, embedding_model)
    register_vector(conn)
    return applied


def check_meta(meta: dict[str, str], embedding_dim: int, embedding_model: str) -> None:
    stored_dim = int(meta.get("embedding_dim", embedding_dim))
    stored_model = meta.get("embedding_model", embedding_model)
    if stored_dim != embedding_dim or stored_model != embedding_model:
        raise SchemaMismatchError(
            f"database was initialised for {stored_model} ({stored_dim}-d) but the current configuration "
            f"is {embedding_model} ({embedding_dim}-d). Re-ingest into a fresh database or restore the "
            "original CITEWELL_EMBEDDING_MODEL / CITEWELL_EMBEDDING_DIM."
        )


def read_meta(conn: psycopg.Connection) -> dict[str, str] | None:
    exists = conn.execute("SELECT to_regclass('citewell_meta') IS NOT NULL").fetchone()
    if not exists or not exists[0]:
        return None
    return {str(k): str(v) for k, v in conn.execute("SELECT key, value FROM citewell_meta").fetchall()}


def pgvector_version(conn: psycopg.Connection) -> tuple[int, ...] | None:
    row = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
    if not row:
        return None
    return tuple(int(p) for p in str(row[0]).split(".") if p.isdigit())
