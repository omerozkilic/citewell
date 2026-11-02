"""Connection pool and a tiny, dependency-free migration runner."""

from __future__ import annotations

import logging
from importlib import resources

import psycopg
from pgvector.psycopg import register_vector
from psycopg_pool import ConnectionPool

log = logging.getLogger(__name__)

MIGRATIONS_PACKAGE = "citewell.migrations"


class SchemaMismatchError(RuntimeError):
    pass


def _configure(conn: psycopg.Connection) -> None:
    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        # Extension not created yet (fresh database before `citewell init`).
        log.debug("pgvector type not registered on this connection yet")
    conn.commit()


def create_pool(url: str, min_size: int = 1, max_size: int = 8) -> ConnectionPool:
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
