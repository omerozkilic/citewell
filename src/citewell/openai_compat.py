"""OpenAI-compatible chat adapter: lets chat UIs (Open WebUI and others) use Citewell.

There is **no generation**. The "assistant message" is the retrieved, cited passages formatted as
Markdown, so the core stays LLM-free and offline (ADR-0002, ADR-0010). The helpers here are pure
functions; the routes live in ``citewell.api``.
"""

import json
import re
import time
import uuid
from collections.abc import Iterator
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from citewell.models import SearchResponse, citation_label

MODEL_ID = "citewell"
"""``citewell`` searches every collection the caller may read; ``citewell:NAME`` searches one."""

_TURKISH = re.compile("[çğıöşüÇĞİÖŞÜ]")


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: str
    content: str | list[dict[str, Any]] | None = None

    def text(self) -> str:
        """Plain text of the message (OpenAI clients may send a list of ``{"type": "text"}`` parts)."""
        if isinstance(self.content, str):
            return self.content
        if isinstance(self.content, list):
            return "\n".join(
                str(part.get("text", ""))
                for part in self.content
                if isinstance(part, dict) and part.get("type") == "text"
            )
        return ""


class ChatRequest(BaseModel):
    """The subset of an OpenAI chat completion request that matters here; other fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    model: str = MODEL_ID
    messages: list[ChatMessage] = Field(min_length=1)
    stream: bool = False
    # Citewell extensions (OpenAI SDKs pass them with ``extra_body``).
    top_k: int | None = Field(default=None, ge=1, le=50)
    mode: Literal["hybrid", "vector", "keyword"] | None = None
    rerank: bool | None = None

    def question(self) -> str:
        """The last user message: earlier turns are not used, each question is searched on its own."""
        for message in reversed(self.messages):
            if message.role == "user" and (text := message.text().strip()):
                return text
        raise ValueError("the request needs a user message with text")

    def collection(self) -> str | None:
        """Collection named by ``model`` (``citewell:NAME``), or ``None`` for all."""
        base, _, name = self.model.partition(":")
        if base != MODEL_ID:
            raise ValueError(f"unknown model: {self.model!r} (use '{MODEL_ID}' or '{MODEL_ID}:<collection>')")
        return name or None


def _quote(text: str) -> str:
    return "\n".join(f"> {line}" if line.strip() else ">" for line in text.strip().splitlines())


def render_answer(resp: SearchResponse) -> str:
    """Markdown message: numbered passages with their quotes, a weak-match note, and a source list."""
    tr = bool(_TURKISH.search(resp.query))
    if not resp.hits:
        return (
            "Eşleşen pasaj bulunamadı. Başka kelimeler veya başka bir koleksiyon deneyin."
            if tr
            else "No matching passages. Try other keywords or another collection."
        )
    blocks = []
    if not resp.answerable:
        blocks.append(
            "> ⚠ Zayıf eşleşme: belgeler bu soruyu büyük olasılıkla yanıtlamıyor. Pasajlara eleştirel bakın."
            if tr
            else "> ⚠ Weak match: the documents probably do not answer this question. Read the passages "
            "critically."
        )
    labels = []
    for h in resp.hits:
        label = citation_label(h.source, h.page, h.section, h.page_label)
        labels.append(f"[{h.rank}] {label}")
        blocks.append(f"**[{h.rank}]** {h.title or h.source}\n{_quote(h.quote)}")
    blocks.append(f"**{'Kaynaklar' if tr else 'Sources'}**\n" + "\n".join(labels))
    return "\n\n".join(blocks)


def completion(
    content: str, model: str, created: int | None = None, cid: str | None = None
) -> dict[str, Any]:
    return {
        "id": cid or f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": created or int(time.time()),
        "model": model,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def stream_events(content: str, model: str) -> Iterator[str]:
    """Server-sent events of an OpenAI streaming response: the role, the text in pieces, then stop."""
    cid, created = f"chatcmpl-{uuid.uuid4().hex[:24]}", int(time.time())

    def chunk(delta: dict[str, str], finish: str | None = None) -> str:
        body = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }
        return f"data: {json.dumps(body, ensure_ascii=False)}\n\n"

    yield chunk({"role": "assistant", "content": ""})
    pieces = content.split("\n\n")
    for i, piece in enumerate(pieces):
        yield chunk({"content": piece + ("\n\n" if i < len(pieces) - 1 else "")})
    yield chunk({}, finish="stop")
    yield "data: [DONE]\n\n"


def model_list(collections: list[str], created: int | None = None) -> dict[str, Any]:
    stamp = created or int(time.time())
    ids = [MODEL_ID, *(f"{MODEL_ID}:{name}" for name in collections)]
    return {
        "object": "list",
        "data": [{"id": i, "object": "model", "created": stamp, "owned_by": "citewell"} for i in ids],
    }
