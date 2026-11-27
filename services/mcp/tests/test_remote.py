"""The remote connector (recallspring-mcp --http): a token on every request, checked with the API, sessions bound
to their token, and the same tools with the request's own token (no network, no database)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from mcp.server.transport_security import TransportSecuritySettings
from starlette.testclient import TestClient

from recallspring_mcp import server
from recallspring_mcp.client import RecallSpringClient
from recallspring_mcp.remote import build_app, security_for

GOOD, OTHER = "rsc_good", "rsc_other"
ACCEPT = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "codex", "version": "1"}},
}


class FakeApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []  # (path, token)

    def handler(self, request: httpx.Request) -> httpx.Response:
        token = request.headers.get("authorization", "")[7:]
        path = request.url.path.removeprefix("/api/v1/connector")
        self.calls.append((path, token))
        if token not in (GOOD, OTHER):
            return httpx.Response(401, json={"code": "connector_token_invalid", "message": "Revoked."})
        if path == "/hello":
            return httpx.Response(200, json={"client": "codex"})
        if path == "/courses":
            return httpx.Response(200, json=[{"id": "k1", "title": f"Course for {token}"}])
        return httpx.Response(404, json={"code": "not_found", "message": "Not found."})


@pytest.fixture
def fake() -> Any:
    api = FakeApi()
    server._remote = True
    yield api
    server._remote = False


@pytest.fixture
def http(fake: FakeApi) -> Any:
    def client_for(token: str) -> RecallSpringClient:
        return RecallSpringClient("http://127.0.0.1:4318", token, transport=httpx.MockTransport(fake.handler))

    security = TransportSecuritySettings(allowed_hosts=["testserver"], allowed_origins=["https://study.example.org"])
    with TestClient(build_app(server.mcp, client_for, security)) as c:
        yield c


def bearer(token: str, session: str | None = None) -> dict[str, str]:
    return {**ACCEPT, "Authorization": f"Bearer {token}", **({"mcp-session-id": session} if session else {})}


def connect(http: TestClient, token: str = GOOD) -> str:
    r = http.post("/mcp", json=INIT, headers=bearer(token))
    assert r.status_code == 200, r.text
    session = r.headers["mcp-session-id"]
    note = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert http.post("/mcp", json=note, headers=bearer(token, session)).status_code == 202
    return session


def call(http: TestClient, token: str, session: str, tool: str) -> httpx.Response:
    body = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": tool, "arguments": {}}}
    return http.post("/mcp", json=body, headers=bearer(token, session))


def test_a_request_without_a_connector_token_is_refused(http: TestClient, fake: FakeApi) -> None:
    r = http.post("/mcp", json=INIT, headers=ACCEPT)
    assert r.status_code == 401 and r.headers["www-authenticate"].startswith("Bearer")
    r = http.post("/mcp", json=INIT, headers=bearer("sk-not-ours"))
    assert r.status_code == 401 and r.json()["error"] == "invalid_token"
    assert fake.calls == []  # neither reached the API


def test_a_revoked_token_is_refused_by_the_api_check(http: TestClient, fake: FakeApi) -> None:
    r = http.post("/mcp", json=INIT, headers=bearer("rsc_revoked"))
    assert r.status_code == 401 and "revoked" in r.json()["error_description"]
    assert fake.calls == [("/hello", "rsc_revoked")]


def test_tools_use_the_token_of_the_request(http: TestClient, fake: FakeApi) -> None:
    session = connect(http)
    r = call(http, GOOD, session, "list_courses")
    assert r.status_code == 200 and "Course for rsc_good" in r.text
    assert fake.calls == [("/hello", GOOD), ("/courses", GOOD)]  # the token is checked once, then remembered


def test_a_session_belongs_to_its_token(http: TestClient, fake: FakeApi) -> None:
    session = connect(http)
    r = call(http, OTHER, session, "list_courses")  # a valid token, but not this session's
    assert r.status_code == 404 and r.json()["error"] == "session_not_found"
    assert ("/courses", OTHER) not in fake.calls and ("/courses", GOOD) not in fake.calls


def test_without_a_request_token_remote_mode_never_reads_a_token_file(fake: FakeApi) -> None:
    with pytest.raises(server.ConnectorError):
        server.get_client()


def test_only_the_public_address_and_this_computer_may_call() -> None:
    s = security_for("https://study.example.org", 4319)
    assert s.allowed_hosts == ["study.example.org", "127.0.0.1:4319", "localhost:4319"]
    assert s.allowed_origins == ["https://study.example.org"] and s.enable_dns_rebinding_protection
