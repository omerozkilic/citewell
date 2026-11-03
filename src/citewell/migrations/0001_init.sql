-- Citewell initial schema.
-- {dim} is substituted with the configured embedding dimension at migration time.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS citewell_meta (
    key   text PRIMARY KEY,
    value text NOT NULL
);

CREATE TABLE IF NOT EXISTS collections (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL UNIQUE CHECK (name ~ '^[a-z0-9][a-z0-9_-]{{0,63}}$'),
    language    text NOT NULL DEFAULT 'turkish' CHECK (language IN ('turkish', 'english', 'simple')),
    description text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    id            bigserial PRIMARY KEY,
    collection_id bigint NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    source        text NOT NULL,
    title         text,
    mime          text,
    sha256        text NOT NULL,
    page_count    int,
    metadata      jsonb NOT NULL DEFAULT '{{}}'::jsonb,
    ingested_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (collection_id, source)
);

CREATE TABLE IF NOT EXISTS chunks (
    id            text PRIMARY KEY,
    document_id   bigint NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    collection_id bigint NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    ord           int NOT NULL,
    page          int,
    section       text,
    char_start    int NOT NULL,
    char_end      int NOT NULL,
    text          text NOT NULL,
    tsv           tsvector NOT NULL,
    embedding     vector({dim}) NOT NULL,
    UNIQUE (document_id, ord)
);

CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS chunks_tsv_gin        ON chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS chunks_collection_idx ON chunks (collection_id);
CREATE INDEX IF NOT EXISTS documents_collection_idx ON documents (collection_id);
