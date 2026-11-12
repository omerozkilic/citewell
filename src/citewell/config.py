"""Runtime configuration.

Every setting can be provided through an environment variable prefixed with
``CITEWELL_`` (for example ``CITEWELL_DATABASE_URL``) or a ``.env`` file.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

SearchMode = Literal["vector", "keyword", "hybrid"]
Language = Literal["turkish", "english", "simple"]
EmbeddingBackend = Literal["sentence-transformers", "hash"]
RerankerBackend = Literal["sentence-transformers", "lexical", "none"]


MAX_QUERY_CHARS = 2000
"""Longest search query accepted by REST and MCP."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CITEWELL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- storage -----------------------------------------------------------
    database_url: str = Field(
        default="postgresql://citewell:citewell@localhost:5432/citewell",
        description="PostgreSQL connection string. The pgvector extension must be available.",
    )
    pool_min_size: int = 1
    pool_max_size: int = 8

    # --- embeddings --------------------------------------------------------
    embedding_backend: EmbeddingBackend = "sentence-transformers"
    embedding_model: str = "BAAI/bge-m3"
    embedding_revision: str | None = Field(
        default=None, description="Pin the embedding model to this Hugging Face commit hash."
    )
    embedding_dim: int = Field(
        default=1024,
        description="Vector dimension. Fixed when the database is initialised.",
    )
    embedding_batch_size: int = 16
    embedding_device: str | None = None  # e.g. "cpu", "cuda", "mps"; None = auto
    max_seq_length: int = 512

    # --- reranking ---------------------------------------------------------
    reranker_backend: RerankerBackend = "sentence-transformers"
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_revision: str | None = Field(
        default=None, description="Pin the reranker to this Hugging Face commit hash."
    )
    rerank_by_default: bool = False
    rerank_candidates: int = 30

    # --- chunking ----------------------------------------------------------
    chunk_size: int = Field(default=1000, description="Target chunk size in characters.")
    chunk_overlap: int = Field(default=150, description="Overlap between chunks in characters.")
    min_chunk_size: int = 40

    # --- search ------------------------------------------------------------
    default_collection: str = "default"
    default_language: Language = "turkish"
    default_mode: SearchMode = "hybrid"
    default_top_k: int = 5
    max_top_k: int = 50
    statement_timeout_ms: int = Field(
        default=15000,
        ge=0,
        description="Abort a search query in PostgreSQL after this many milliseconds (0 = no limit).",
    )
    candidate_pool: int = Field(default=40, description="Per-retriever candidates fed into RRF.")
    rrf_k: int = 60
    quote_max_chars: int = 320
    fold_diacritics: bool = Field(
        default=True,
        description="Keyword search ignores diacritics, so 'ogrenci izni' finds 'öğrenci izni'.",
    )

    # --- servers -----------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000
    api_token: SecretStr | None = Field(
        default=None,
        description="When set, REST and HTTP MCP endpoints require 'Authorization: Bearer <token>'.",
    )
    max_upload_mb: int = 50
    max_document_pages: int = Field(
        default=5000, ge=0, description="Reject PDFs with more pages (0 = no limit)."
    )
    max_unpacked_mb: int = Field(
        default=200, ge=0, description="Reject DOCX files that unpack to more than this (0 = no limit)."
    )
    max_zip_ratio: int = Field(
        default=200, ge=0, description="Reject DOCX files compressed more than this ratio (0 = no limit)."
    )
    allowed_hosts: list[str] = Field(
        default_factory=list,
        description="Extra Host headers accepted by the HTTP MCP endpoint (DNS-rebinding protection).",
    )

    preload_models: bool = Field(
        default=True,
        description="Load the embedding model in the background when a server starts, "
        "so the first query does not wait for it.",
    )

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("chunk_overlap")
    @classmethod
    def _overlap_smaller_than_chunk(cls, v: int, info: object) -> int:
        data = getattr(info, "data", {})
        size = data.get("chunk_size", 1000)
        if v >= size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
