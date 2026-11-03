# ADR-0002: No LLM in the core — return cited passages, not answers

- **Status:** Accepted
- **Date:** 2026-11-02

## Context

The consumers of Citewell are AI assistants (Claude Desktop, Claude Code, Cursor) that already have a
strong LLM. Calling a second LLM inside the retrieval server would add an API key, cost, latency, a
network dependency and a second place where hallucinations can happen.

## Decision

Citewell never calls an LLM. Every response is a list of passages with **source, page/section, chunk
id, score, a verbatim quote and the full chunk text**. Answer synthesis and citation formatting are
left to the calling assistant, guided by MCP server instructions and the `answer_with_citations`
prompt.

## Consequences

- Works fully offline with no API key; deterministic and cheap to evaluate (pure retrieval metrics).
- Answer quality depends on the client model — acceptable, since that is the model the user chose.
- A future OpenAI-compatible endpoint (for UIs such as Open WebUI) will be an *optional* adapter that
  delegates generation to a user-configured model; the core stays LLM-free.

## Alternatives considered

- Built-in answer generation (classic RAG chatbot) — duplicates the assistant, needs keys, harder to
  evaluate.
