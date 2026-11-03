# ADR-0006: Page-aware chunking with verbatim slices and stable chunk ids

- **Status:** Accepted
- **Date:** 2026-11-02

## Context

A citation is only useful if it points to the right place. Chunkers that concatenate pages or
rewrite text produce page numbers and quotes that cannot be verified.

## Decision

- Loaders emit *pages* (PDF pages, form-feed separated text) or *sections* (Markdown/DOCX headings,
  with the heading path as `section`).
- The chunker packs sentence-ish units up to `chunk_size` characters (default 1000) with whole-sentence
  overlap (default 150), **never crossing a page**, and stores `char_start`/`char_end` so that
  `chunk.text == page.text[start:end]` always holds.
- Chunk ids are `sha1(collection, source, sha256(file), ordinal)[:20]`: re-ingesting identical bytes
  yields identical ids, so citations stay stable; changed files get new ids.
- Ingest is idempotent by file hash; changed documents are replaced atomically.
- Quotes returned to assistants are selected from the chunk's own sentences, never generated.

## Consequences

- Page hit rate is measurable (it is one of the eval metrics).
- Very short pages produce short chunks; this is accepted in exchange for exact citations.
