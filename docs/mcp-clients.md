# Connect an assistant

Citewell speaks MCP over two transports:

- **stdio** — `citewell mcp`; the client starts the process.
- **Streamable HTTP** — `http://localhost:8000/mcp`, served by `citewell serve` / Docker Compose.

## Claude Code

```bash
# installed from PyPI (uv tool install "citewell[models]")
claude mcp add -s user citewell -- citewell mcp
# HTTP, server running via Docker Compose or `citewell serve`
claude mcp add -s user --transport http citewell http://localhost:8000/mcp
# stdio from a checkout
claude mcp add -s user citewell -- uv --directory /path/to/citewell run citewell mcp
```

Then ask: *"citewell'de uzaktan çalışma kurallarını ara ve kaynak göstererek özetle"*.

## Claude Desktop

Settings → Developer → Edit config (`claude_desktop_config.json`):

=== "PyPI install"

    Claude Desktop does not see your shell's `PATH`; use the full path from `which citewell`.

    ```json
    {
      "mcpServers": {
        "citewell": {
          "command": "/Users/you/.local/bin/citewell",
          "args": ["mcp"],
          "env": {
            "CITEWELL_DATABASE_URL": "postgresql://citewell:citewell@localhost:5432/citewell"
          }
        }
      }
    }
    ```

=== "Docker"

    ```json
    {
      "mcpServers": {
        "citewell": {
          "command": "docker",
          "args": ["exec", "-i", "citewell-citewell-1", "citewell", "mcp"]
        }
      }
    }
    ```

=== "Local checkout"

    ```json
    {
      "mcpServers": {
        "citewell": {
          "command": "uv",
          "args": ["--directory", "/path/to/citewell", "run", "citewell", "mcp"],
          "env": {
            "CITEWELL_DATABASE_URL": "postgresql://citewell:citewell@localhost:5432/citewell",
            "HF_HUB_OFFLINE": "1"
          }
        }
      }
    }
    ```

Restart Claude Desktop; the tools appear under the 🔌 menu.

## Cursor

`.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global):

```json
{ "mcpServers": { "citewell": { "url": "http://localhost:8000/mcp" } } }
```

## Authentication

If `CITEWELL_API_TOKEN` is set, HTTP clients must send `Authorization: Bearer <token>`:

```bash
claude mcp add --transport http citewell http://localhost:8000/mcp --header "Authorization: Bearer $TOKEN"
```

## Tools, resources and prompts

| Kind | Name | Notes |
|---|---|---|
| tool | `search_documents` | `query`, `top_k` (1–50), `collection` (`*` = all), `mode` (`hybrid`/`vector`/`keyword`), `rerank`, `source_prefix` |
| tool | `get_chunk` | `chunk_id`, `context` (0–5 neighbouring chunks) |
| tool | `verify_quote` | `quote`, optional `chunk_id` / `source` / `collection`; returns `verified`, `match` (`exact`, `normalized`, `ellipsis`, `fuzzy`, `not_found`), the exact `source_text` and its citation |
| tool | `list_collections` | name, language, document and chunk counts |
| tool | `list_documents` | per collection |
| resource | `citewell://collections` | JSON |
| resource | `citewell://chunks/{chunk_id}` | plain text with a citation header |
| prompt | `answer_with_citations` | `question`, `collection` |

All tools are annotated `readOnlyHint: true` and return structured JSON (with an output schema) as
well as text. The server's instructions ask the assistant to cite with `[n]` markers, finish with a
*Kaynaklar / Sources* list, and to treat passage content as data, not instructions.

## Quote verification

Paraphrasing inside quotation marks is the most common way an assistant misquotes a source.
`verify_quote` checks a quotation before it is shown:

| `match` | Meaning | `verified` |
|---|---|---|
| `exact` | occurs verbatim (whitespace ignored) | ✅ |
| `normalized` | differs only in letter case (Turkish-aware), quote marks or dashes | ✅ |
| `ellipsis` | parts separated by `…` / `...` occur in order on the same page | ✅ |
| `fuzzy` | not verbatim, but a very similar passage exists — returned in `source_text` | ❌ |
| `not_found` | nothing similar in the searched documents | ❌ |

Pass the `chunk_id` the quote came from for the fastest, most precise check; without it Citewell
searches all collections. Strict matching scans whole documents; the fuzzy fallback looks at the
most relevant pages only.
