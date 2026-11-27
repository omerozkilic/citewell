# ADR-0008: Scoped API tokens

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

`CITEWELL_API_TOKEN` is one shared secret that grants access to every collection and to ingest and
delete. Teams that share a server need to give an assistant, a colleague or a script access to some
collections only, and to revoke it without rotating everyone's secret.

## Decision

- Tokens are created with `citewell tokens create NAME (-c COLLECTION ... | --all-collections) [--write]`,
  listed with `tokens list` and revoked with `tokens revoke NAME`. The token is printed once; the
  database (`api_tokens`, migration 0004) stores only its SHA-256, a plain fast hash being enough for a
  256-bit random value.
- A token's scope is a set of collections (or all) plus a `read`/`write` flag. Read means search,
  verify, chunks, collection and document listings; write means REST upload and delete.
- The HTTP middleware authenticates every request except `/health`, puts the scope in a context
  variable, and the REST routes and MCP tools read it from there, so both transports share one
  implementation (`citewell.auth`). Out-of-scope requests fail with 403 (MCP: a tool error with the
  reason); listings are filtered instead of rejected.
- `CITEWELL_API_TOKEN` keeps working and is unrestricted, as do the CLI and stdio MCP.
- Without `CITEWELL_API_TOKEN` the server stays open until the first token is created; from then on a
  valid token is required. A database that predates the tokens table counts as having none.
- MCP tools stay read-only (ADR-0007). A write token only affects the REST endpoints.

## Consequences

- Revocation is immediate (the token is looked up on every request).
- A request with no collection is limited to the default collection when the token may read it, and
  to the token's collections otherwise; `"*"` expands to the token's collections.
- Rate limiting and an audit log need this token identity and follow as separate changes.
