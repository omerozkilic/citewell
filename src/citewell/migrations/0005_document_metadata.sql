-- Basic document metadata for search filters: author, document date and free-form tags.
-- New rows get them from the loaders (author, date) and from `ingest --tag`; the author of
-- documents ingested earlier is back-filled from the stored loader metadata. Re-ingest with
-- `--force` to pick up dates.
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS author   text,
    ADD COLUMN IF NOT EXISTS doc_date date,
    ADD COLUMN IF NOT EXISTS tags     text[] NOT NULL DEFAULT '{{}}';

UPDATE documents SET author = NULLIF(btrim(metadata->>'author'), '') WHERE author IS NULL;

CREATE INDEX IF NOT EXISTS documents_tags_gin ON documents USING gin (tags);
