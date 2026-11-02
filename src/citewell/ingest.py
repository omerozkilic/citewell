"""Ingestion pipeline: load → chunk → embed → store (idempotent by content hash)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from pathlib import Path

from citewell.chunking import chunk_pages
from citewell.config import Settings
from citewell.embeddings import Embedder
from citewell.loaders import UnsupportedFormatError, iter_files, load_bytes
from citewell.models import ChunkDraft, Collection, IngestResult, LoadedDocument
from citewell.store import Store

log = logging.getLogger(__name__)

ProgressFn = Callable[[IngestResult], None]


def embedding_text(doc: LoadedDocument, chunk: ChunkDraft) -> str:
    """Text that is embedded for a chunk: a short context header plus the chunk itself.

    Prepending title/section ("contextual chunk headers") noticeably helps short
    chunks whose subject is only stated in a heading.
    """
    header = " — ".join(x for x in (doc.title, chunk.section) if x)
    return f"{header}\n{chunk.text}" if header else chunk.text


class IngestService:
    def __init__(self, store: Store, embedder: Embedder, settings: Settings):
        self.store = store
        self.embedder = embedder
        self.settings = settings

    def collection(self, name: str | None, language: str | None = None) -> Collection:
        return self.store.ensure_collection(
            name or self.settings.default_collection, language or self.settings.default_language
        )

    def ingest_document(
        self, doc: LoadedDocument, collection: Collection, force: bool = False
    ) -> IngestResult:
        if not force and self.store.document_sha(collection.id, doc.source) == doc.sha256:
            return IngestResult(source=doc.source, status="unchanged", pages=len(doc.pages))
        chunks = chunk_pages(
            doc.pages,
            chunk_size=self.settings.chunk_size,
            overlap=self.settings.chunk_overlap,
            min_size=self.settings.min_chunk_size,
        )
        if not chunks:
            return IngestResult(
                source=doc.source,
                status="skipped",
                message="no extractable text (scanned PDF? OCR is not supported yet)",
            )
        vectors = self.embedder.embed_documents([embedding_text(doc, c) for c in chunks])
        doc_id = self.store.replace_document(collection, doc, chunks, vectors)
        pages = len({c.page for c in chunks if c.page is not None})
        return IngestResult(
            source=doc.source, status="ingested", document_id=doc_id, chunks=len(chunks), pages=pages
        )

    def ingest_bytes(
        self,
        data: bytes,
        source: str,
        collection: str | None = None,
        language: str | None = None,
        force: bool = False,
    ) -> IngestResult:
        col = self.collection(collection, language)
        try:
            doc = load_bytes(data, source)
        except UnsupportedFormatError as exc:
            return IngestResult(source=source, status="error", message=str(exc))
        return self.ingest_document(doc, col, force=force)

    def ingest_paths(
        self,
        paths: Iterable[Path],
        collection: str | None = None,
        language: str | None = None,
        force: bool = False,
        recursive: bool = True,
        on_result: ProgressFn | None = None,
    ) -> list[IngestResult]:
        col = self.collection(collection, language)
        results: list[IngestResult] = []
        for path, source in iter_files(paths, recursive=recursive):
            try:
                doc = load_bytes(path.read_bytes(), source)
                res = self.ingest_document(doc, col, force=force)
            except Exception as exc:  # keep going; report per-file errors
                log.exception("failed to ingest %s", path)
                res = IngestResult(source=source, status="error", message=f"{type(exc).__name__}: {exc}")
            results.append(res)
            if on_result:
                on_result(res)
        return results
