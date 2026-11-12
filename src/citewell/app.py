"""Application container: wires settings, database, models and services together.

Models are loaded lazily and only once per process, so ``citewell --help`` or a
health check never pays the model-loading cost.
"""

from __future__ import annotations

import logging
import threading
from functools import cached_property
from typing import TYPE_CHECKING

from psycopg_pool import ConnectionPool

from citewell import db
from citewell.config import Settings, get_settings
from citewell.embeddings import Embedder, build_embedder
from citewell.hub import prefer_offline
from citewell.ingest import IngestService
from citewell.rerank import Reranker, build_reranker
from citewell.search import SearchService
from citewell.store import Store

if TYPE_CHECKING:
    from citewell.verify import QuoteVerifier

log = logging.getLogger(__name__)


class Citewell:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._lock = threading.Lock()
        self._embedder: Embedder | None = None
        self._reranker: Reranker | None = None
        self._reranker_loaded = False

    # ---------------------------------------------------------------- database

    @cached_property
    def pool(self) -> ConnectionPool:
        s = self.settings
        return db.create_pool(s.database_url, s.pool_min_size, s.pool_max_size)

    @cached_property
    def store(self) -> Store:
        return Store(self.pool, self.settings.statement_timeout_ms)

    @property
    def embedding_model_id(self) -> str:
        s = self.settings
        return f"hash-{s.embedding_dim}" if s.embedding_backend == "hash" else s.embedding_model

    def init_db(self) -> list[str]:
        return self.store.migrate(self.settings.embedding_dim, self.embedding_model_id)

    def check_schema(self) -> None:
        meta = self.store.meta()
        if meta is None:
            raise db.SchemaMismatchError("database is not initialised; run `citewell init` first")
        db.check_meta(meta, self.settings.embedding_dim, self.embedding_model_id)
        with self.store.conn() as conn:
            pending = db.pending_migrations(conn)
        if pending:
            # Migrations are additive; apply them so an upgraded install keeps working.
            log.info("applying pending migrations: %s", ", ".join(pending))
            self.init_db()

    # ------------------------------------------------------------------ models

    def _prefer_offline(self) -> None:
        """Switch the Hugging Face client to offline mode when every needed model is cached."""
        s = self.settings
        needed = []
        if s.embedding_backend == "sentence-transformers":
            needed.append(s.embedding_model)
        if s.reranker_backend == "sentence-transformers":
            needed.append(s.reranker_model)
        if needed:
            prefer_offline(needed)

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            with self._lock:
                if self._embedder is None:
                    self._prefer_offline()
                    s = self.settings
                    self._embedder = build_embedder(
                        s.embedding_backend,
                        s.embedding_model,
                        s.embedding_dim,
                        device=s.embedding_device,
                        batch_size=s.embedding_batch_size,
                        max_seq_length=s.max_seq_length,
                        revision=s.embedding_revision,
                    )
        return self._embedder

    @property
    def reranker(self) -> Reranker | None:
        if not self._reranker_loaded:
            with self._lock:
                if not self._reranker_loaded:
                    self._prefer_offline()
                    s = self.settings
                    self._reranker = build_reranker(
                        s.reranker_backend, s.reranker_model, s.embedding_device, revision=s.reranker_revision
                    )
                    self._reranker_loaded = True
        return self._reranker

    # ---------------------------------------------------------------- services

    @property
    def search(self) -> SearchService:
        # The reranker is resolved lazily inside SearchService only when needed.
        return _LazyRerankSearch(self)

    @property
    def ingest(self) -> IngestService:
        return IngestService(self.store, self.embedder, self.settings)

    @property
    def verifier(self) -> QuoteVerifier:
        from citewell.verify import QuoteVerifier

        return QuoteVerifier(self.store, self.search)

    def preload(self) -> threading.Thread | None:
        """Warm up the embedding model (and the reranker if it is on by default) in the background."""
        s = self.settings
        if not s.preload_models or s.embedding_backend == "hash":
            return None

        def run() -> None:
            try:
                _ = self.embedder
                if s.rerank_by_default:
                    _ = self.reranker
                log.info("models loaded")
            except Exception:
                log.warning("model preload failed; models will load on first use", exc_info=True)

        thread = threading.Thread(target=run, name="citewell-preload", daemon=True)
        thread.start()
        return thread

    def close(self) -> None:
        if "pool" in self.__dict__:
            self.pool.close()


class _LazyRerankSearch(SearchService):
    """SearchService that loads the embedder / reranker only when a query needs them."""

    def __init__(self, app: Citewell):
        self._app = app
        self.store = app.store
        self.settings = app.settings

    @property
    def embedder(self) -> Embedder:
        return self._app.embedder

    @property
    def reranker(self) -> Reranker | None:
        if self.settings.reranker_backend == "none":
            return None
        return self._app.reranker
