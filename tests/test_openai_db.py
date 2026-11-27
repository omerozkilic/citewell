"""POST /v1/chat/completions and GET /v1/models against the sample corpora."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from citewell import auth
from citewell.api import create_app
from citewell.app import Citewell

from .conftest import make_settings

pytestmark = pytest.mark.db

ASK = "Parolalar en az kaç karakter uzunluğunda olmalıdır?"


@pytest.fixture
def client(citewell: Citewell) -> Iterator[TestClient]:
    with TestClient(create_app(Citewell(make_settings()), mount_mcp=False)) as c:
        yield c


def chat(client: TestClient, question: str = ASK, **extra: Any) -> Any:
    body = {"model": "citewell", "messages": [{"role": "user", "content": question}], **extra}
    return client.post("/v1/chat/completions", json=body)


def test_chat_returns_cited_passages_as_the_answer(client: TestClient) -> None:
    r = chat(client)
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "chat.completion" and body["model"] == "citewell"
    message = body["choices"][0]["message"]
    assert message["role"] == "assistant" and body["choices"][0]["finish_reason"] == "stop"
    assert "**[1]**" in message["content"] and "**Kaynaklar**" in message["content"]
    assert "14 karakter" in message["content"] and "bilgi-guvenligi-politikasi.md" in message["content"]


def test_chat_stream(client: TestClient) -> None:
    r = chat(client, stream=True)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    lines = [ln for ln in r.text.split("\n\n") if ln]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(ln.removeprefix("data: ")) for ln in lines[:-1]]
    text = "".join(c["choices"][0]["delta"].get("content", "") for c in chunks)
    assert "14 karakter" in text and chunks[-1]["choices"][0]["finish_reason"] == "stop"


def test_model_selects_a_collection_and_extensions_are_honoured(client: TestClient) -> None:
    en = chat(client, "When does the on-call rotation hand over?", model="citewell:handbook-en").json()
    assert "on-call-handbook.md" in en["choices"][0]["message"]["content"]
    assert "bilgi-guvenligi" not in en["choices"][0]["message"]["content"]
    one = chat(client, top_k=1, mode="keyword", rerank=False).json()["choices"][0]["message"]["content"]
    assert "**[1]**" in one and "**[2]**" not in one


def test_weak_match_is_flagged(client: TestClient) -> None:
    text = chat(client, "Dünyanın en yüksek dağı hangisidir?").json()["choices"][0]["message"]["content"]
    assert text.startswith("> ⚠ Zayıf eşleşme")


def test_errors(client: TestClient) -> None:
    assert client.post("/v1/chat/completions", json={"model": "citewell", "messages": []}).status_code == 422
    bad = client.post("/v1/chat/completions", json={"messages": [{"role": "assistant", "content": "x"}]})
    assert bad.status_code == 400 and "user message" in bad.json()["detail"]
    assert chat(client, model="gpt-4o").status_code == 400
    assert chat(client, "x" * 2001).status_code == 400
    assert chat(client, model="citewell:nope").status_code == 404


def test_models_lists_the_collections(client: TestClient) -> None:
    body = client.get("/v1/models").json()
    ids = [m["id"] for m in body["data"]]
    assert body["object"] == "list" and ids[0] == "citewell"
    assert {"citewell:default", "citewell:handbook-en"} <= set(ids)


def test_token_is_the_api_key_and_scope_applies(citewell: Citewell) -> None:
    secret = auth.new_token()
    citewell.store.create_token("chat-reader", auth.hash_token(secret), ["default"], False)
    try:
        app = create_app(Citewell(make_settings(api_token="admin-secret")), mount_mcp=False)
        with TestClient(app) as c:
            body = {"model": "citewell", "messages": [{"role": "user", "content": ASK}]}
            assert c.post("/v1/chat/completions", json=body).status_code == 401
            assert c.get("/v1/models").status_code == 401
            headers = {"Authorization": f"Bearer {secret}"}
            ok = c.post("/v1/chat/completions", json=body, headers=headers)
            assert ok.status_code == 200 and "14 karakter" in ok.json()["choices"][0]["message"]["content"]
            assert [m["id"] for m in c.get("/v1/models", headers=headers).json()["data"]] == [
                "citewell",
                "citewell:default",
            ]
            denied = c.post(
                "/v1/chat/completions", json={**body, "model": "citewell:handbook-en"}, headers=headers
            )
            assert denied.status_code == 403
    finally:
        citewell.store.revoke_token("chat-reader")
