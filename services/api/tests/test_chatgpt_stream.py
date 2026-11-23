"""Chat replies shown as they arrive (/ai/chatgpt/messages/stream): the learner's message is saved first, pieces of
text and RecallSpring steps follow, the completed reply is saved like a waited-for one, failures are saved and
reported as an event, and problems found before ChatGPT is asked stay ordinary errors."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from recallspring_api.ai import siwc

from .conftest import Api
from .test_chatgpt_signin import FakeOpenAI, install_fake_openai, reply_events, sign_in
from .test_chatgpt_tools import ToolFake, calls
from .test_chatgpt_tools import fake as tool_fake  # noqa: F401 (fixture)


@pytest.fixture
def openai(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> FakeOpenAI:
    return install_fake_openai(monkeypatch, tmp_path)


def stream(api: Api, body: dict[str, Any], key: str | None = None) -> tuple[Any, list[dict[str, Any]]]:
    r = api.client.post("/api/v1/ai/chatgpt/messages/stream", json=body, headers=api.headers(key))
    events = [json.loads(line) for line in r.text.splitlines() if line.strip()] if r.status_code == 200 else []
    return r, events


def test_the_reply_arrives_in_pieces_and_is_saved_whole(owner_api: Api, openai: FakeOpenAI) -> None:
    sign_in(owner_api, openai)
    openai.events = reply_events("Hello there!", 1)
    r, events = stream(owner_api, {"model": "gpt-test", "message": "Hi"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    assert r.headers["cache-control"] == "no-store"
    kinds = [e["type"] for e in events]
    assert kinds == ["saved", "text", "text", "done"]
    assert "".join(e["text"] for e in events if e["type"] == "text") == "Hello there!"
    conv = events[-1]["conversation"]
    assert conv["id"] == events[0]["conversation_id"]
    assert [(m["role"], m["text"]) for m in conv["messages"]] == [("user", "Hi"), ("assistant", "Hello there!")]
    assert conv["messages"][1]["model"] == "gpt-test-2026-11-01"
    # the same as reading the conversation afterwards
    assert owner_api.get(f"/ai/chatgpt/conversations/{conv['id']}").json() == conv


def test_a_retried_stream_never_asks_twice(owner_api: Api, openai: FakeOpenAI) -> None:
    sign_in(owner_api, openai)
    openai.events = reply_events("Once.")
    key = str(uuid.uuid4())
    _, first = stream(owner_api, {"model": "gpt-test", "message": "Hi"}, key)
    _, again = stream(owner_api, {"model": "gpt-test", "message": "Hi"}, key)
    assert [e["type"] for e in again] == ["saved", "done"]
    assert again[-1]["conversation"] == first[-1]["conversation"]
    assert len([q for q in openai.requests if q.url.path == "/v1/responses"]) == 1


def test_a_failed_reply_is_saved_and_reported_without_any_fallback(owner_api: Api, openai: FakeOpenAI) -> None:
    sign_in(owner_api, openai)
    openai.events = [
        {"type": "response.output_text.delta", "delta": "Par"},
        {"type": "response.failed", "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}},
    ]
    _, events = stream(owner_api, {"model": "gpt-test", "message": "Hi"})
    assert [e["type"] for e in events] == ["saved", "text", "error"]
    error = events[-1]
    assert error["status"] == 429 and error["code"] == "chatgpt_usage_limit"
    assert "never switches to paid API usage" in error["message"]
    conv_id = error["details"]["conversation_id"]
    saved = owner_api.get(f"/ai/chatgpt/conversations/{conv_id}").json()["messages"]
    assert [(m["role"], m["text"], m["error_code"]) for m in saved] == [("user", "Hi", "usage_limit")]  # no part kept


def test_problems_before_asking_are_ordinary_errors(owner_api: Api, openai: FakeOpenAI) -> None:
    r, _ = stream(owner_api, {"model": "gpt-test", "message": "Hi"})
    assert r.status_code == 409 and r.json()["code"] == "chatgpt_not_connected"
    bare = owner_api.client.post("/api/v1/ai/chatgpt/messages/stream", json={"model": "gpt-test", "message": "Hi"})
    assert bare.status_code == 403  # CSRF as for every write
    assert not [q for q in openai.requests if q.url.path == "/v1/responses"]


def test_recallspring_steps_show_as_they_run(owner_api: Api, tool_fake: ToolFake) -> None:  # noqa: F811
    sign_in(owner_api, tool_fake)
    ids = owner_api.course_with_question()
    tool_fake.rounds = [
        calls(1, ("c1", "get_course_outline", {"course_id": ids["course_id"]}), text="Let me look."),
        reply_events("Your course has one source.", 2),
    ]
    _, events = stream(owner_api, {"model": "gpt-test", "message": "What is in my course?", "recallspring": True})
    kinds = [e["type"] for e in events]
    assert kinds[0] == "saved" and kinds[-1] == "done"
    step = next(e for e in events if e["type"] == "step")["step"]
    assert step["name"] == "get_course_outline" and step["status"] == "ok"
    assert kinds.index("step") < max(i for i, k in enumerate(kinds) if k == "text")  # the step came mid-reply
    shown = "".join(e["text"] for e in events if e["type"] == "text")
    saved = events[-1]["conversation"]["messages"][-1]["text"]
    assert shown == saved == "Let me look.\n\nYour course has one source."


def test_pieces_reach_the_browser_before_the_reply_is_complete(owner_api: Api, openai: FakeOpenAI) -> None:
    """Nothing on the way buffers the reply: OpenAI's second half is held back until the first half was received."""
    sign_in(owner_api, openai)
    received_first = threading.Event()

    def sse() -> Iterator[bytes]:
        events = reply_events("First half. Second half.")
        for e in events[:2]:
            yield f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode()
        assert received_first.wait(10), "the first piece did not reach the browser while the reply was running"
        for e in events[2:]:
            yield f"event: {e['type']}\ndata: {json.dumps(e)}\n\n".encode()

    handle = openai.handle

    def slow(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/responses":
            openai.requests.append(request)
            return httpx.Response(200, content=sse(), headers={"content-type": "text/event-stream"})
        return handle(request)

    siwc.transport = httpx.MockTransport(slow)
    body = {"model": "gpt-test", "message": "Hi"}
    seen: list[dict[str, Any]] = []
    with owner_api.client.stream(
        "POST", "/api/v1/ai/chatgpt/messages/stream", json=body, headers=owner_api.headers()
    ) as r:
        for line in r.iter_lines():
            if line.strip():
                seen.append(json.loads(line))
                if seen[-1]["type"] == "text":
                    received_first.set()
    assert [e["type"] for e in seen] == ["saved", "text", "text", "done"]
    assert seen[-1]["conversation"]["messages"][1]["text"] == "First half. Second half."
