"""Domain models shared by the CLI, REST API and MCP server."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Page(BaseModel):
    """A unit of extracted text. ``number`` is 1-based, ``None`` for unpaged formats."""

    number: int | None
    text: str
    section: str | None = None
    label: str | None = None  # printed page label from the PDF (e.g. "iv", "12"), if it differs
    ocr: bool = False  # text was recognised from an image (OCR), not read from a text layer


class LoadedDocument(BaseModel):
    source: str
    title: str
    mime: str
    sha256: str
    pages: list[Page]
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChunkDraft(BaseModel):
    ord: int
    page: int | None
    page_label: str | None = None
    section: str | None
    char_start: int
    char_end: int
    text: str


class Collection(BaseModel):
    id: int
    name: str
    language: str
    description: str | None = None
    document_count: int = 0
    chunk_count: int = 0
    created_at: datetime | None = None


class DocumentInfo(BaseModel):
    id: int
    collection: str
    source: str
    title: str | None
    mime: str | None
    sha256: str
    page_count: int | None
    pages_without_text: int | None = Field(
        default=None, description="PDF pages with no text layer (scanned?) — not searchable."
    )
    ocr_pages: list[int] | None = Field(
        default=None, description="PDF pages whose text was recognised by OCR (approximate)."
    )
    chunk_count: int = 0
    ingested_at: datetime | None = None


class Citation(BaseModel):
    """Everything an assistant needs to cite a passage."""

    source: str = Field(description="Document path relative to the ingest root (or uploaded filename).")
    title: str | None = None
    page: int | None = Field(default=None, description="1-based page number, if the format has pages.")
    page_label: str | None = Field(default=None, description="Printed page label, if it differs.")
    section: str | None = None
    chunk_id: str
    quote: str = Field(description="Verbatim excerpt from the chunk that best matches the query.")

    def label(self) -> str:
        if self.page is not None:
            loc = f"s. {self.page}"
            if self.page_label and self.page_label != str(self.page):
                loc = f"s. {self.page_label} (PDF s. {self.page})"
        else:
            loc = self.section or ""
        return f"{self.source}{', ' + loc if loc else ''}"


class SearchHit(BaseModel):
    rank: int
    score: float
    chunk_id: str
    collection: str
    document_id: int
    source: str
    title: str | None
    page: int | None
    page_label: str | None = None
    section: str | None
    text: str
    quote: str
    scores: dict[str, float] = Field(
        default_factory=dict, description="Per-retriever scores/ranks (vector, keyword, rrf, rerank)."
    )

    @property
    def citation(self) -> Citation:
        return Citation(
            source=self.source,
            title=self.title,
            page=self.page,
            page_label=self.page_label,
            section=self.section,
            chunk_id=self.chunk_id,
            quote=self.quote,
        )


class SearchResponse(BaseModel):
    query: str
    mode: str
    reranked: bool
    collections: list[str]
    took_ms: float
    hits: list[SearchHit]


class ChunkRecord(BaseModel):
    chunk_id: str
    collection: str
    document_id: int
    source: str
    title: str | None
    ord: int
    page: int | None
    section: str | None
    char_start: int
    char_end: int
    text: str
    page_label: str | None = None


def citation_label(source: str, page: int | None, section: str | None, page_label: str | None = None) -> str:
    """Human-readable location: ``file, s. 12``, ``file, s. iv (PDF s. 4)`` or ``file § Section``."""
    if page is not None:
        if page_label and page_label != str(page):
            return f"{source}, s. {page_label} (PDF s. {page})"
        return f"{source}, s. {page}"
    if section:
        return f"{source} § {section}"
    return source


class QuoteCheck(BaseModel):
    """Result of checking a quote against the indexed documents."""

    verified: bool = Field(
        description="True if the quote occurs in the source (exact, normalized or ellipsis)."
    )
    match: Literal["exact", "normalized", "ellipsis", "fuzzy", "not_found"]
    similarity: float = Field(description="1.0 for verified quotes; character similarity for fuzzy matches.")
    quote: str
    source_text: str | None = Field(
        default=None, description="The exact wording in the document (closest passage if not verified)."
    )
    citation: str | None = None
    source: str | None = None
    title: str | None = None
    page: int | None = None
    page_label: str | None = None
    section: str | None = None
    chunk_id: str | None = None
    collection: str | None = None
    pages_searched: int = 0
    note: str


class IngestResult(BaseModel):
    source: str
    status: str  # "ingested" | "unchanged" | "skipped" | "error"
    document_id: int | None = None
    chunks: int = 0
    pages: int = 0
    message: str | None = None
