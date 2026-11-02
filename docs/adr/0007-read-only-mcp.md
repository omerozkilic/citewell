# ADR-0007: MCP-first, read-only tool surface

- **Status:** Accepted
- **Date:** 2026-11-02

## Context

MCP is the main product surface. Assistants read untrusted document content, which may contain
prompt-injection payloads.

## Decision

- The MCP server exposes only read operations: `search_documents`, `get_chunk`, `list_collections`,
  `list_documents`, resources `citewell://collections` and `citewell://chunks/{id}`, and the
  `answer_with_citations` prompt. All tools carry `readOnlyHint` annotations and return structured
  output (JSON schema) as well as text.
- Ingestion and deletion are available only through the CLI and the (optionally token-protected)
  REST API, i.e. actions a human initiates.
- Transports: stdio (`citewell mcp`) for desktop clients and Streamable HTTP mounted at `/mcp` in the
  REST server (stateless, JSON responses) with DNS-rebinding protection.
- Built on the official MCP Python SDK v2 (`MCPServer`).

## Consequences

- A malicious document cannot make an assistant alter the index through Citewell.
- Users who want "add this file to my memory" from chat must use the CLI/REST for now; a future
  opt-in ingest tool would require explicit configuration and an ADR.
