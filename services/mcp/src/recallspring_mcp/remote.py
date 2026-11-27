"""Remote connector (2026-11-27): the same tools over MCP streamable HTTP at ``/mcp``, for an assistant that runs on
another computer than RecallSpring (Codex and Antigravity connect from that computer; Claude from Anthropic's cloud).

Every request carries a connector token (``Authorization: Bearer rsc_...``). The RecallSpring API checks it as it
checks any connector request: stored there only as a hash, revocable in Settings, counted towards the daily limit
and recorded in History. This process keeps no secrets of its own: only, in memory, which tokens the API accepted
in the last few minutes and which MCP session belongs to which token, so one token cannot use another's session.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .client import RecallSpringClient

TOKEN_PREFIX = "rsc_"
MAX_TOKEN_CHARS = 200
SESSION_HEADER = b"mcp-session-id"

request_client: contextvars.ContextVar[RecallSpringClient | None] = contextvars.ContextVar(
    "recallspring_request_client", default=None
)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


Header = tuple[bytes, bytes]


async def _json(send: Send, status: int, error: str, description: str, *headers: Header) -> None:
    data = json.dumps({"error": error, "error_description": description}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode()), *headers],
        }
    )
    await send({"type": "http.response.body", "body": data})


CHALLENGE: Header = (b"www-authenticate", b'Bearer realm="RecallSpring"')
INVALID: Header = (b"www-authenticate", b'Bearer realm="RecallSpring", error="invalid_token"')
NEEDED = "A RecallSpring connector token is needed."
NOT_OURS = "This is not a RecallSpring connector token."
REVOKED = "This connector token is invalid or was revoked. Make a new one in RecallSpring: Settings, Assistants."
LIMIT = "RecallSpring's daily connector limit is reached. Change it in Settings or continue tomorrow."
DOWN = "RecallSpring is not reachable right now. Try again later."
NO_SESSION = "Unknown session; connect again."


class TokenGate:
    """ASGI middleware in front of the MCP app: a connector token on every request, checked with the API."""

    def __init__(
        self,
        app: ASGIApp,
        client_for: Callable[[str], RecallSpringClient],
        *,
        recheck_seconds: float = 300.0,
        max_sessions: int = 1000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.app = app
        self.client_for = client_for
        self.recheck_seconds = recheck_seconds
        self.max_sessions = max_sessions
        self.clock = clock
        self.clients: dict[str, RecallSpringClient] = {}
        self.accepted: dict[str, float] = {}  # token digest -> when the API last accepted it
        self.sessions: OrderedDict[str, str] = OrderedDict()  # MCP session id -> token digest

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # lifespan
            await self.app(scope, receive, send)
            return
        headers = dict(scope["headers"])
        auth = headers.get(b"authorization", b"").decode("latin-1")
        token = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
        if not token:
            await _json(send, 401, "invalid_request", NEEDED, CHALLENGE)
            return
        if not token.startswith(TOKEN_PREFIX) or len(token) > MAX_TOKEN_CHARS:
            await _json(send, 401, "invalid_token", NOT_OURS, INVALID)
            return
        digest = _digest(token)
        if self.clock() - self.accepted.get(digest, float("-inf")) > self.recheck_seconds:
            client = self.clients.get(digest) or self.client_for(token)
            status = await client.check()
            if status != 200:
                self.accepted.pop(digest, None)
                if self.clients.pop(digest, None) is None:
                    await client.aclose()
                await self._refuse(send, status)
                return
            self.clients[digest] = client
            self.accepted[digest] = self.clock()
        client = self.clients[digest]
        session = headers.get(SESSION_HEADER, b"").decode("latin-1")
        if session and self.sessions.get(session) != digest:
            await _json(send, 404, "session_not_found", NO_SESSION)
            return

        async def remember_session(message: Message) -> None:
            if message["type"] == "http.response.start" and not session:
                new = dict(message.get("headers", [])).get(SESSION_HEADER)
                if new:
                    self.sessions[new.decode("latin-1")] = digest
                    while len(self.sessions) > self.max_sessions:
                        self.sessions.popitem(last=False)
            await send(message)

        reset = request_client.set(client)  # a new session's server task keeps the client of the request that began it
        try:
            await self.app(scope, receive, remember_session)
        finally:
            request_client.reset(reset)

    async def _refuse(self, send: Send, status: int) -> None:
        if status in (401, 403):
            await _json(send, 401, "invalid_token", REVOKED, INVALID)
        elif status == 429:
            await _json(send, 429, "daily_limit", LIMIT)
        else:
            await _json(send, 503, "unavailable", DOWN)


def security_for(public_url: str, port: int) -> TransportSecuritySettings:
    """Only the public address and this computer may call (DNS rebinding protection stays on)."""
    parts = urlsplit(public_url)
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[parts.netloc, f"127.0.0.1:{port}", f"localhost:{port}"],
        allowed_origins=[f"{parts.scheme}://{parts.netloc}"],
    )


def build_app(
    mcp: Any,
    client_for: Callable[[str], RecallSpringClient],
    security: TransportSecuritySettings,
    **gate: Any,
) -> TokenGate:
    """The MCP app at /mcp behind the token gate. JSON responses (no event stream): simpler behind a proxy."""
    inner = mcp.streamable_http_app(streamable_http_path="/mcp", json_response=True, transport_security=security)
    return TokenGate(inner, client_for, **gate)
