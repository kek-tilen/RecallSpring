"""Sign in with ChatGPT against a fake OpenAI (no network, no real account): PKCE sign-in with dynamic client
registration, protected token storage, model discovery, allowlisted streamed requests with saved conversations and
reply details, refresh, plan-usage errors without any fallback, and signing out."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import time
import uuid
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import select

from recallspring_api.ai import siwc, siwc_store
from recallspring_api.config import get_settings
from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent

from .conftest import Api

SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"


def _b64(data: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def id_token(nonce: str, client_id: str, **claims: Any) -> str:
    payload = {
        "iss": "https://auth.openai.com",
        "aud": client_id,
        "sub": "user-123",
        "email": "learner@example.com",
        "name": "Learner",
        "nonce": nonce,
        "exp": time.time() + 3600,
        **claims,
    }
    return f"{_b64({'alg': 'RS256'})}.{_b64(payload)}.signature"


class FakeOpenAI:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.tokens: list[tuple[int, dict[str, Any]]] = []
        self.models: dict[str, Any] = {
            "models": [
                {"slug": "gpt-test", "display_name": "GPT Test", "visibility": "list"},
                {"slug": "gpt-hidden", "display_name": "Hidden", "visibility": "hide"},
            ]
        }
        self.events: list[dict[str, Any]] = []
        self.responses_status = 200
        self.responses_body: Any = None

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/api/accounts/oauth/token":
            status, body = self.tokens.pop(0)
            return httpx.Response(status, json=body)
        if path == "/v1/models":
            return httpx.Response(200, json=self.models)
        if path == "/v1/responses":
            if self.responses_status != 200:
                return httpx.Response(self.responses_status, json=self.responses_body)
            text = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in self.events)
            return httpx.Response(200, content=text.encode(), headers={"content-type": "text/event-stream"})
        if path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={"revocation_endpoint": "https://auth.openai.com/oauth/revoke"})
        if path == "/oauth/revoke":
            return httpx.Response(200)
        return httpx.Response(404)

    def form(self, request: httpx.Request) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


@pytest.fixture
def openai(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> FakeOpenAI:
    monkeypatch.setattr(get_settings(), "secrets_dir", tmp_path / "secrets")
    monkeypatch.setattr(siwc, "is_local", lambda host: True)  # the test client calls itself "testserver"
    fake = FakeOpenAI()
    monkeypatch.setattr(siwc, "transport", httpx.MockTransport(fake.handle))
    siwc._pending.clear()
    return fake


def sign_in(api: Api, fake: FakeOpenAI, client_id: str = "oaiapp_test", scopes: str = SCOPES) -> tuple[dict, Any]:
    r = api.post("/ai/chatgpt/connect")
    assert r.status_code == 200, r.text
    q = {k: v[0] for k, v in parse_qs(urlsplit(r.json()["authorize_url"]).query).items()}
    fake.tokens.append(
        (
            200,
            {
                "access_token": "at-1",
                "refresh_token": "rt-1",
                "id_token": id_token(q["nonce"], client_id),
                "expires_in": 3600,
                "scope": scopes,
                "token_type": "Bearer",
            },
        )
    )
    params = {"state": q["state"], "code": "code-1", "client_id": client_id, "scope": scopes}
    callback = api.client.get("/api/v1/ai/chatgpt/callback", params=params, follow_redirects=False)
    return q, callback


def _audits(action: str) -> list[AuditEvent]:
    with new_session() as db:
        return list(db.scalars(select(AuditEvent).where(AuditEvent.action == action)))


def test_sign_in_registers_once_keeps_tokens_private_and_returns_to_settings(
    owner_api: Api, openai: FakeOpenAI
) -> None:
    assert owner_api.get("/ai/chatgpt").json()["connected"] is False
    q, callback = sign_in(owner_api, openai)
    assert q["client_id"] == "dynamic_agent_client" and q["agent_name_hint"] == "RecallSpring"
    assert q["ext_agent_host_id"].startswith("urn:uuid:") and q["code_challenge_method"] == "S256"
    assert q["redirect_uri"].startswith("http://127.0.0.1:") and q["redirect_uri"].endswith(
        "/api/v1/ai/chatgpt/callback"
    )
    assert "chatgpt.tokens.use.direct" in q["scope"].split() and q["resource"] == "https://api.openai.com/v1"
    assert callback.status_code == 303 and callback.headers["location"].endswith("/settings?chatgpt=connected#chatgpt")

    exchange = openai.form(openai.requests[0])
    assert exchange["grant_type"] == "authorization_code" and exchange["client_id"] == "oaiapp_test"
    assert exchange["redirect_uri"] == q["redirect_uri"] and exchange["resource"] == "https://api.openai.com/v1"
    challenge = base64.urlsafe_b64encode(hashlib.sha256(exchange["code_verifier"].encode()).digest()).rstrip(b"=")
    assert challenge.decode() == q["code_challenge"]

    status = owner_api.get("/ai/chatgpt")
    assert (
        status.json()["connected"] and status.json()["plan_usage"] and status.json()["email"] == "learner@example.com"
    )
    assert "at-1" not in status.text and "rt-1" not in status.text
    files = list((get_settings().secrets_dir).glob("chatgpt-*.bin"))
    assert len(files) == 1
    raw = files[0].read_bytes()
    if os.name == "nt":
        assert raw.startswith(siwc_store.DPAPI_MAGIC) and b"at-1" not in raw
    else:
        assert files[0].stat().st_mode & 0o077 == 0

    again = owner_api.post("/ai/chatgpt/connect").json()["authorize_url"]
    q2 = {k: v[0] for k, v in parse_qs(urlsplit(again).query).items()}
    assert q2["client_id"] == "oaiapp_test" and "agent_name_hint" not in q2  # a returning sign-in
    assert q2["ext_agent_host_id"] == q["ext_agent_host_id"]
    forged = owner_api.client.get(
        "/api/v1/ai/chatgpt/callback",
        params={"state": q2["state"], "code": "c", "client_id": "oaiapp_other"},
        follow_redirects=False,
    )
    assert forged.headers["location"].endswith("chatgpt=error#chatgpt")  # a different client id is refused
    replay = owner_api.client.get(
        "/api/v1/ai/chatgpt/callback", params={"state": q2["state"], "code": "c"}, follow_redirects=False
    )
    assert replay.headers["location"] == "/settings?chatgpt=expired#chatgpt"  # state is single-use
    events = _audits("ai.chatgpt_sign_in")
    assert [e.details["outcome"] for e in events] == ["connected", "error"]
    assert all("at-1" not in json.dumps(e.details) for e in events)


def reply_events(text: str, n: int = 1) -> list[dict[str, Any]]:
    half = len(text) // 2
    return [
        {"type": "response.created", "response": {"id": f"resp_{n}"}},
        {"type": "response.output_text.delta", "delta": text[:half]},
        {"type": "response.output_text.delta", "delta": text[half:]},
        {
            "type": "response.completed",
            "response": {
                "id": f"resp_{n}",
                "model": "gpt-test-2026-11-01",
                "usage": {
                    "input_tokens": 40,
                    "input_tokens_details": {"cached_tokens": 8},
                    "output_tokens": 12,
                    "output_tokens_details": {"reasoning_tokens": 5},
                    "total_tokens": 52,
                    "secret": "never kept",
                },
            },
        },
    ]


def test_models_and_saved_replies_send_only_allowed_fields(owner_api: Api, openai: FakeOpenAI) -> None:
    sign_in(owner_api, openai)
    assert owner_api.get("/ai/chatgpt/models").json() == [{"slug": "gpt-test", "display_name": "GPT Test"}]
    assert openai.requests[-1].headers["authorization"] == "Bearer at-1"

    openai.events = reply_events("Hello!", 1)
    first = owner_api.post("/ai/chatgpt/messages", {"model": "gpt-test", "message": "Hi"})
    assert first.status_code == 200, first.text
    conv = first.json()
    assert conv["title"] == "Hi" and [m["role"] for m in conv["messages"]] == ["user", "assistant"]
    answer = conv["messages"][1]
    assert answer["text"] == "Hello!" and answer["model_requested"] == "gpt-test"
    assert answer["model"] == "gpt-test-2026-11-01" and answer["response_id"] == "resp_1"
    assert answer["usage"] == {
        "input_tokens": 40,
        "cached_tokens": 8,
        "output_tokens": 12,
        "reasoning_tokens": 5,
        "total_tokens": 52,
    }
    assert answer["account"] == "learner@example.com" and isinstance(answer["duration_ms"], int)
    assert answer["completed_at"] and conv["totals"]["total_tokens"] == 52

    openai.events = reply_events("Still here.", 2)
    body = {"conversation_id": conv["id"], "model": "gpt-test", "message": "And now?"}
    second = owner_api.post("/ai/chatgpt/messages", body)
    assert second.status_code == 200, second.text
    sent = json.loads(openai.requests[-1].content)
    assert list(sent) == ["model", "instructions", "input", "store", "stream"]
    assert sent["store"] is False and sent["stream"] is True and sent["model"] == "gpt-test"
    assert [(i["role"], i["content"][0]["type"], i["content"][0]["text"]) for i in sent["input"]] == [
        ("user", "input_text", "Hi"),
        ("assistant", "output_text", "Hello!"),
        ("user", "input_text", "And now?"),
    ]
    assert {urlsplit(str(req.url)).hostname for req in openai.requests} <= {"auth.openai.com", "api.openai.com"}
    listed = owner_api.get("/ai/chatgpt/conversations").json()
    assert [c["replies"] for c in listed["conversations"]] == [2]
    assert listed["usage"]["last_30_days"] == {
        "replies": 2,
        "input_tokens": 80,
        "output_tokens": 24,
        "total_tokens": 104,
    }
    events = _audits("ai.chatgpt_message")
    assert [e.details["outcome"] for e in events] == ["completed", "completed"]
    assert all("And now" not in json.dumps(e.details) for e in events)  # no message text in the audit log


def test_a_retried_request_never_asks_twice(owner_api: Api, openai: FakeOpenAI) -> None:
    sign_in(owner_api, openai)
    openai.events = reply_events("Once.")
    key = str(uuid.uuid4())
    body = {"model": "gpt-test", "message": "Hi"}
    a = owner_api.post("/ai/chatgpt/messages", body, key=key)
    b = owner_api.post("/ai/chatgpt/messages", body, key=key)
    assert a.json() == b.json() and len(b.json()["messages"]) == 2
    assert len([r for r in openai.requests if r.url.path == "/v1/responses"]) == 1


def test_plan_usage_problems_stop_the_request_without_any_fallback(owner_api: Api, openai: FakeOpenAI) -> None:
    sign_in(owner_api, openai)
    body: dict[str, Any] = {"model": "gpt-test", "message": "Hi"}
    openai.events = [
        {"type": "response.output_text.delta", "delta": "Par"},
        {"type": "response.failed", "response": {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}},
    ]
    limit = owner_api.post("/ai/chatgpt/messages", body)
    assert limit.status_code == 429 and limit.json()["code"] == "chatgpt_usage_limit"
    assert "never switches to paid API usage" in limit.json()["message"]
    conv_id = limit.json()["details"]["conversation_id"]
    saved = owner_api.get(f"/ai/chatgpt/conversations/{conv_id}").json()["messages"]
    assert [(m["role"], m["text"], m["error_code"]) for m in saved] == [("user", "Hi", "usage_limit")]  # kept

    body = {**body, "conversation_id": conv_id}
    openai.events = [{"type": "response.output_text.delta", "delta": "Cut"}]
    cut = owner_api.post("/ai/chatgpt/messages", body)
    assert cut.status_code == 502 and cut.json()["code"] == "chatgpt_interrupted"

    openai.responses_status, openai.responses_body = 503, {"detail": "direct routing unavailable"}
    down = owner_api.post("/ai/chatgpt/messages", body)
    assert down.status_code == 503 and down.json()["code"] == "chatgpt_unavailable"

    openai.responses_status = 403
    openai.responses_body = {"error": {"code": "subscription_sharing_user_not_eligible"}}
    assert owner_api.post("/ai/chatgpt/messages", body).json()["code"] == "chatgpt_not_eligible"
    calls = [r for r in openai.requests if r.url.path == "/v1/responses"]
    assert len(calls) == 4  # one call per press: no retries and no other provider

    openai.responses_status = 200
    openai.events = reply_events("Hello")
    ok = owner_api.post("/ai/chatgpt/messages", {**body, "message": "Hi again"})
    assert ok.status_code == 200
    sent = json.loads(openai.requests[-1].content)["input"]
    assert [i["content"][0]["text"] for i in sent] == ["Hi again"]  # failed messages are not sent again
    codes = [m["error_code"] for m in ok.json()["messages"]]
    assert codes == ["usage_limit", "interrupted", "unavailable", "not_eligible", None, None]

    _, callback = sign_in(owner_api, openai, scopes="openid profile email offline_access")
    assert callback.headers["location"].endswith("chatgpt=no_plan_usage#chatgpt")
    assert owner_api.get("/ai/chatgpt").json()["plan_usage"] is False
    refused = owner_api.post("/ai/chatgpt/messages", body)
    assert refused.status_code == 409 and refused.json()["code"] == "chatgpt_plan_usage_not_enabled"


def test_tokens_are_refreshed_and_a_revoked_sign_in_ends_cleanly(owner_api: Api, openai: FakeOpenAI) -> None:
    sign_in(owner_api, openai)
    user_id = next(iter(get_settings().secrets_dir.glob("chatgpt-*.bin"))).stem.removeprefix("chatgpt-")
    uid = uuid.UUID(user_id)
    record = siwc_store.load(uid)
    siwc_store.save(uid, {**record, "expires_at": time.time() - 10})
    openai.tokens.append((200, {"access_token": "at-2", "refresh_token": "rt-2", "expires_in": 3600}))
    assert owner_api.get("/ai/chatgpt/models").status_code == 200
    refresh = openai.form(openai.requests[-2])
    assert refresh == {
        "grant_type": "refresh_token",
        "client_id": "oaiapp_test",
        "refresh_token": "rt-1",
        "resource": "https://api.openai.com/v1",
    }
    assert openai.requests[-1].headers["authorization"] == "Bearer at-2"
    assert siwc_store.load(uid)["refresh_token"] == "rt-2"  # rotated

    siwc_store.save(uid, {**siwc_store.load(uid), "expires_at": time.time() - 10})
    openai.tokens.append((400, {"error": "invalid_grant"}))
    ended = owner_api.get("/ai/chatgpt/models")
    assert ended.status_code == 409 and ended.json()["code"] == "chatgpt_signed_out"
    status = owner_api.get("/ai/chatgpt").json()
    assert status["connected"] is False and status["registered"] is True  # the next sign-in is a returning one


def test_sign_out_revokes_at_openai_and_deletes_the_tokens(owner_api: Api, openai: FakeOpenAI) -> None:
    sign_in(owner_api, openai)
    r = owner_api.post("/ai/chatgpt/disconnect")
    assert r.status_code == 200 and r.json()["revoked"] is True and r.json()["connected"] is False
    revoke = openai.form(openai.requests[-1])
    assert revoke == {"token": "rt-1", "token_type_hint": "refresh_token", "client_id": "oaiapp_test"}
    assert owner_api.post("/ai/chatgpt/messages", {"model": "gpt-test", "message": "Hi"}).json()["code"] == (
        "chatgpt_not_connected"
    )
    assert _audits("ai.chatgpt_disconnected")[0].details == {"revoked_at_openai": True}


def test_conversations_stay_after_signing_out_of_chatgpt_and_recallspring(owner_api: Api, openai: FakeOpenAI) -> None:
    sign_in(owner_api, openai)
    openai.events = reply_events("Hello!")
    conv = owner_api.post("/ai/chatgpt/messages", {"model": "gpt-test", "message": "Hi"}).json()

    # Signing out of RecallSpring and back in keeps the ChatGPT sign-in.
    assert owner_api.client.post("/api/v1/auth/logout", headers=owner_api.headers()).status_code == 204
    assert owner_api.get("/ai/chatgpt").status_code == 401
    assert owner_api.login("owner").status_code == 200
    assert owner_api.get("/ai/chatgpt").json()["connected"] is True

    # Signing out of ChatGPT ends the sign-in but keeps the conversations, readable and continued after signing in.
    owner_api.post("/ai/chatgpt/disconnect")
    assert owner_api.get("/ai/chatgpt").json()["connected"] is False
    assert [c["id"] for c in owner_api.get("/ai/chatgpt/conversations").json()["conversations"]] == [conv["id"]]
    assert len(owner_api.get(f"/ai/chatgpt/conversations/{conv['id']}").json()["messages"]) == 2
    sign_in(owner_api, openai)
    openai.events = reply_events("Welcome back.", 2)
    more = owner_api.post(
        "/ai/chatgpt/messages", {"conversation_id": conv["id"], "model": "gpt-test", "message": "Back"}
    )
    assert more.status_code == 200 and len(more.json()["messages"]) == 4


def test_deleting_a_conversation_is_soft_and_restorable(owner_api: Api, openai: FakeOpenAI) -> None:
    sign_in(owner_api, openai)
    openai.events = reply_events("Hello!")
    conv = owner_api.post("/ai/chatgpt/messages", {"model": "gpt-test", "message": "Hi"}).json()
    gone = owner_api.client.delete(f"/api/v1/ai/chatgpt/conversations/{conv['id']}", headers=owner_api.headers())
    assert gone.status_code == 200 and gone.json()["conversations"] == []
    assert [c["id"] for c in gone.json()["deleted"]] == [conv["id"]]
    blocked = owner_api.post(
        "/ai/chatgpt/messages", {"conversation_id": conv["id"], "model": "gpt-test", "message": "x"}
    )
    assert blocked.status_code == 409 and blocked.json()["code"] == "conversation_deleted"
    back = owner_api.post(f"/ai/chatgpt/conversations/{conv['id']}/restore")
    assert [c["id"] for c in back.json()["conversations"]] == [conv["id"]] and back.json()["deleted"] == []
    assert len(_audits("ai.chatgpt_conversation_deleted")) == 1
    assert len(_audits("ai.chatgpt_conversation_restored")) == 1
    assert owner_api.get(f"/ai/chatgpt/conversations/{uuid.uuid4()}").status_code == 404
    renamed = owner_api.patch(f"/ai/chatgpt/conversations/{conv['id']}", {"title": "  Quality\n assurance "})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Quality assurance"
    assert owner_api.patch(f"/ai/chatgpt/conversations/{conv['id']}", {"title": ""}).status_code == 422


def test_declined_sign_in_and_remote_servers(
    owner_api: Api, openai: FakeOpenAI, monkeypatch: pytest.MonkeyPatch
) -> None:
    q = {
        k: v[0]
        for k, v in parse_qs(urlsplit(owner_api.post("/ai/chatgpt/connect").json()["authorize_url"]).query).items()
    }
    declined = owner_api.client.get(
        "/api/v1/ai/chatgpt/callback", params={"state": q["state"], "error": "access_denied"}, follow_redirects=False
    )
    assert declined.headers["location"].endswith("chatgpt=declined#chatgpt")
    assert openai.requests == []  # nothing was exchanged

    monkeypatch.setattr(siwc, "is_local", lambda host: host in siwc.LOOPBACK)
    remote = owner_api.post("/ai/chatgpt/connect")
    assert remote.status_code == 409 and remote.json()["code"] == "chatgpt_not_local"
    assert owner_api.get("/ai/chatgpt").json()["unavailable_reason"] == "not_local"


def test_the_access_log_never_shows_the_authorization_code() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", "/api/v1/ai/chatgpt/callback?code=secret&state=s", "1.1", 303),
        None,
    )
    siwc.RedactCallbackQuery().filter(record)
    assert "secret" not in record.getMessage() and "?[redacted]" in record.getMessage()


def test_replies_carry_checked_visuals_and_the_learner_can_switch_them_off(owner_api: Api, openai: FakeOpenAI) -> None:
    sign_in(owner_api, openai)
    flow = {
        "type": "process_flow",
        "title": "PDCA",
        "alt_text": "Plan leads to Do.",
        "data": {
            "nodes": [{"id": "p", "label": "Plan"}, {"id": "d", "label": "Do"}],
            "edges": [{"from": "p", "to": "d"}],
        },
    }
    good = f"```recallspring-visual\n{json.dumps(flow)}\n```"
    text = f"Here it is.\n\n{good}\n\n```recallspring-visual\n<script>x</script>\n```"
    openai.events = reply_events(text)
    conv = owner_api.post("/ai/chatgpt/messages", {"model": "gpt-test", "message": "Show PDCA"}).json()
    reply = conv["messages"][1]
    assert reply["text"] == text  # saved exactly as written
    assert [v["ok"] for v in reply["visuals"]] == [True, False]
    assert reply["visuals"][0]["block"]["title"] == "PDCA"
    assert "recallspring-visual" in json.loads(openai.requests[-1].content)["instructions"]
    assert _audits("ai.chatgpt_message")[0].details["visuals"] == [True, False]

    openai.events = reply_events("Plain.", 2)
    owner_api.post(
        "/ai/chatgpt/messages",
        {"conversation_id": conv["id"], "model": "gpt-test", "message": "No pictures", "visuals": False},
    )
    sent = json.loads(openai.requests[-1].content)
    assert "recallspring-visual" not in sent["instructions"] and list(sent) == [
        "model",
        "instructions",
        "input",
        "store",
        "stream",
    ]
