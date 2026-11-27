# ADR-0010: OpenAI-compatible chat adapter that returns passages

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

People without an MCP client want to use Citewell from a chat UI such as Open WebUI, which talks to
OpenAI-style endpoints. ADR-0002 keeps the core free of LLM calls, offline and keyless. Issue #23 listed
three options:

1. `/v1/chat/completions` that returns the retrieved, cited passages as the "answer" (no generation).
2. A proxy that retrieves with Citewell and forwards to a user-configured model (for example Ollama).
3. Only document how to use the UI's own RAG or MCP support against Citewell's REST and MCP endpoints.

## Decision

Option 1. `POST /v1/chat/completions` and `GET /v1/models` are added to the REST API.

- The **last user message** is the search query; earlier turns and system prompts are ignored. The reply is
  one assistant message in Markdown: numbered passages with their verbatim quotes, a weak-match note when the
  [answerability signal](0009-answerability-signal.md) says so, and a source list (file, page or section).
  Streaming (`stream: true`) sends the same text as server-sent events.
- `model` selects the scope: `citewell` searches every collection the token may read, `citewell:NAME` one
  collection. `GET /v1/models` lists them, so a UI shows a collection picker as a model picker. Optional
  extensions `top_k`, `mode` and `rerank` pass through `extra_body`.
- The bearer token is the OpenAI API key, so scoped tokens, rate limiting, the audit log and metrics apply
  unchanged. The adapter is read-only.
- No generation, so no API key, no network and no hallucination are introduced; the response is as
  deterministic as search. Usage counts are zero.

Option 2 stays possible later as a separate, opt-in component; it would need its own ADR because it
adds a network dependency and an LLM to the request path. Option 3 remains the recommendation for users
who want generated answers: Open WebUI can call Citewell over MCP with its own model.

## Consequences

- A chat UI becomes a citation-first search front end: it shows what the documents say, not a synthesised
  answer. This is also the honest behaviour for an offline, LLM-free server.
- Follow-up questions are not resolved from the conversation ("and the second one?" searches those words).
- UIs that send background requests (title or tag generation) trigger extra searches; point their task
  model elsewhere or switch those features off (see the setup guide).
- ADR-0002's note about an adapter that delegates generation to a user-configured model is superseded: the
  adapter does not generate.
