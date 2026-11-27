"""The OpenAI-compatible adapter: formatting and request handling (no database)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from citewell.models import SearchHit, SearchResponse
from citewell.openai_compat import (
    ChatRequest,
    completion,
    model_list,
    render_answer,
    stream_events,
)


def hit(
    rank: int, source: str = "kilavuz.pdf", page: int | None = 3, quote: str = "Parola 14 karakter olmalı."
) -> SearchHit:
    return SearchHit(
        rank=rank, score=0.5, chunk_id=f"c{rank}", collection="default", document_id=1, source=source,
        title="El Kitabı" if rank == 1 else None, page=page, section=None, text=quote, quote=quote,
    )  # fmt: skip


def response(query: str, hits: list[SearchHit], answerable: bool = True) -> SearchResponse:
    return SearchResponse(
        query=query, mode="hybrid", reranked=False, collections=["default"], took_ms=1, hits=hits,
        confidence=0.9, answerable=answerable,
    )  # fmt: skip


def test_answer_lists_passages_quotes_and_sources() -> None:
    text = render_answer(response("password length?", [hit(1), hit(2, "b.md", None, "line one\n\nline two")]))
    assert text.startswith("**[1]** El Kitabı\n> Parola 14 karakter olmalı.")
    assert "**[2]** b.md\n> line one\n>\n> line two" in text
    assert text.endswith("**Sources**\n[1] kilavuz.pdf, s. 3\n[2] b.md")
    assert "Weak match" not in text


def test_answer_is_turkish_for_turkish_questions_and_flags_weak_matches() -> None:
    text = render_answer(response("Parolam kaç karakter olmalı?", [hit(1)], answerable=False))
    assert text.startswith("> ⚠ Zayıf eşleşme") and "**Kaynaklar**" in text
    weak_en = render_answer(response("password", [hit(1)], answerable=False))
    assert weak_en.startswith("> ⚠ Weak match")


def test_no_hits() -> None:
    assert render_answer(response("password", [])).startswith("No matching passages")
    assert render_answer(response("şifre", [])).startswith("Eşleşen pasaj bulunamadı")


def test_request_uses_the_last_user_message() -> None:
    req = ChatRequest.model_validate(
        {
            "model": "citewell:hukuk",
            "messages": [
                {"role": "system", "content": "be nice"},
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "answer"},
                {"role": "user", "content": [{"type": "text", "text": "second"}, {"type": "image_url", "image_url": {}}]},
            ],
            "temperature": 0.2,
            "stream": True,
            "top_k": 3,
        }
    )  # fmt: skip
    assert req.question() == "second" and req.collection() == "hukuk" and req.stream and req.top_k == 3


def test_request_validation() -> None:
    assert ChatRequest.model_validate({"messages": [{"role": "user", "content": "x"}]}).collection() is None
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"messages": []})
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"messages": [{"role": "user", "content": "x"}], "top_k": 0})
    with pytest.raises(ValueError, match="needs a user message"):
        ChatRequest.model_validate({"messages": [{"role": "assistant", "content": "x"}]}).question()
    with pytest.raises(ValueError, match="needs a user message"):
        ChatRequest.model_validate({"messages": [{"role": "user", "content": None}]}).question()
    with pytest.raises(ValueError, match="unknown model"):
        ChatRequest.model_validate(
            {"model": "gpt-4o", "messages": [{"role": "user", "content": "x"}]}
        ).collection()


def test_completion_shape() -> None:
    body = completion("hello", "citewell", created=1, cid="chatcmpl-x")
    assert body["object"] == "chat.completion" and body["id"] == "chatcmpl-x" and body["created"] == 1
    assert body["choices"] == [
        {"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}
    ]
    assert body["usage"]["total_tokens"] == 0
    assert completion("x", "citewell")["id"].startswith("chatcmpl-")


def test_stream_events_follow_the_openai_format() -> None:
    events = list(stream_events("first\n\nsecond", "citewell"))
    assert events[-1] == "data: [DONE]\n\n"
    chunks = [json.loads(e.removeprefix("data: ")) for e in events[:-1]]
    assert all(c["object"] == "chat.completion.chunk" and c["model"] == "citewell" for c in chunks)
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant", "content": ""}
    assert "".join(c["choices"][0]["delta"].get("content", "") for c in chunks) == "first\n\nsecond"
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop" and chunks[-1]["choices"][0]["delta"] == {}
    assert len({c["id"] for c in chunks}) == 1


def test_model_list() -> None:
    ids = [m["id"] for m in model_list(["a", "b"], created=5)["data"]]
    assert ids == ["citewell", "citewell:a", "citewell:b"]
    assert model_list([])["object"] == "list"
