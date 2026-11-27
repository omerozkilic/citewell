# Chat UIs (Open WebUI and others)

Citewell speaks enough of the OpenAI API for chat UIs to use it as a model. There is **no generation**:
the "answer" is the retrieved, cited passages (see [ADR-0010](adr/0010-openai-compatible-adapter.md)).
Everything stays offline and needs no LLM key.

## Open WebUI, step by step

!!! note
    Menu names are from recent Open WebUI versions and may differ in yours. The same two values (base URL and
    key) work in any client that accepts an OpenAI-compatible connection. The endpoints themselves were tested
    with the official `openai` Python client, including streaming.

1. Start Citewell and make sure it has documents (`citewell ingest ./docs -c handbook`). If Open WebUI runs
   in Docker, Citewell must be reachable from the container: bind it to all interfaces
   (`CITEWELL_HOST=0.0.0.0`) or run both in the same Compose network, and add the host name Open WebUI
   uses to `CITEWELL_ALLOWED_HOSTS` if you also use the MCP endpoint.
2. Create a token (recommended once the port is reachable by others):
   `citewell tokens create open-webui -c handbook` (read-only, one collection) or set `CITEWELL_API_TOKEN`.
3. In Open WebUI open **Admin Settings → Connections → OpenAI API → +** and enter:
   - URL: `http://<citewell-host>:8000/v1`
   - Key: the token (any text if the server has no token)
4. Save. The model list now shows `citewell` (all collections you may read) and `citewell:handbook`,
   one per collection. Pick one in a new chat and ask a question.
5. Recommended: **Admin Settings → Interface**: switch off title, tag and follow-up generation, or choose
   another task model. Those are background requests and would otherwise be searched as questions.

The reply lists the passages with their quotes and a **Sources** block, for example:

```
**[1]** Bilgi Güvenliği Politikası
> Parola Kuralları Parolalar en az 14 karakter uzunluğunda olmalıdır. …

**Kaynaklar**
[1] bilgi-guvenligi-politikasi.md § Bilgi Güvenliği Politikası > Parola Kuralları
```

A weak match starts with a `⚠` note ("the documents probably do not answer this question").

## Behaviour

| | |
|---|---|
| Endpoints | `GET /v1/models`, `POST /v1/chat/completions` (JSON and `stream: true`) |
| Query | the last user message (max 2000 characters); earlier turns are not used |
| `model` | `citewell` = every readable collection, `citewell:NAME` = one collection |
| Extras | `top_k` (1-50), `mode` (`hybrid`, `vector`, `keyword`), `rerank` through `extra_body` |
| Auth | `Authorization: Bearer <token>`; scoped tokens, rate limits, audit log and metrics apply |
| Language | the labels follow the question: Turkish for Turkish letters, otherwise English |

Try it with the official client:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="<token>")
reply = client.chat.completions.create(
    model="citewell:handbook",
    messages=[{"role": "user", "content": "Parolalar en az kaç karakter olmalı?"}],
    extra_body={"top_k": 3},
)
print(reply.choices[0].message.content)
```

## Want generated answers?

Use your UI's own model together with Citewell over **MCP** (see [Connect an assistant](mcp-clients.md)),
or call `POST /v1/search` from your own pipeline. The model writes the answer; Citewell supplies the
passages, the `verify_quote` check and the citations.
