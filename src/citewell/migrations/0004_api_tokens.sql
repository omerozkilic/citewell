-- Scoped API tokens for the HTTP server. Only the SHA-256 of a token is stored; a NULL
-- `collections` array means "all collections".
CREATE TABLE IF NOT EXISTS api_tokens (
    id          serial PRIMARY KEY,
    name        text NOT NULL,
    token_hash  text NOT NULL UNIQUE,
    collections text[],
    can_write   boolean NOT NULL DEFAULT false,
    created_at  timestamptz NOT NULL DEFAULT now(),
    revoked_at  timestamptz
);

CREATE UNIQUE INDEX IF NOT EXISTS api_tokens_active_name ON api_tokens (name) WHERE revoked_at IS NULL;
