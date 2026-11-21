"""Sign in with ChatGPT (SIWC): proof of concept for open-source, locally hosted apps (docs/04 Gate 0).

Follows OpenAI's SIWC documentation for open-source apps as read on 2026-11-21 (developers.openai.com/siwc/...):

- OpenID Connect with PKCE (S256) against auth.openai.com; dynamic client registration (``dynamic_agent_client`` with
  ``agent_name_hint`` on the first sign-in, the issued ``client_id`` afterwards) and a per-computer
  ``ext_agent_host_id``. The redirect is HTTP loopback on 127.0.0.1 only, so this works while RecallSpring runs on
  the learner's own computer. No client secret, no API key.
- Plan usage needs the ``chatgpt.tokens.use.direct`` scope; it is checked before every request.
- Models come from GET /v1/models with the user's token; replies from POST /v1/responses with ``store: false``,
  ``stream: true``, ``instructions`` and the whole app-owned history in ``input``. The request body is built from an
  allowlist; fields the preview rejects (temperature, max_output_tokens, metadata, previous_response_id, ...) can
  never be sent. Only ``response.completed`` counts as success.
- Plan usage errors stop the request with a clear status. There is no fallback to any other billing path.

Nothing here runs in the background: every call starts from the learner pressing a button. This module is not yet
used for tutoring or grading; docs/10 records when it may be.

The ID token is received directly from the token endpoint over TLS, so its claims (issuer, audience, expiry, nonce)
are checked without verifying the signature (OpenID Connect Core 3.1.3.7); it is only used to show which account is
connected. Tokens are stored by siwc_store and never returned to the browser or logged.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx

from ..config import get_settings
from . import siwc_store as store

APP_NAME = "RecallSpring"
CALLBACK_PATH = "/api/v1/ai/chatgpt/callback"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = f"openid profile email offline_access resource.invoke {PLAN_SCOPE}"
LOOPBACK = {"127.0.0.1", "localhost", "::1", "[::1]"}
PENDING_SECONDS = 600
REFRESH_MARGIN_SECONDS = 120
MAX_HISTORY = 20
# Fields the SIWC preview accepts that RecallSpring sends; everything else is left out on purpose.
REQUEST_FIELDS = ("model", "instructions", "input", "store", "stream")
TERMINAL_REFRESH = {
    "invalid_grant",
    "invalid_refresh_token",
    "token_expired",
    "refresh_token_expired",
    "refresh_token_invalidated",
    "refresh_token_reused",
}

# Tests replace this with an httpx.MockTransport; in normal use httpx talks to OpenAI over TLS.
transport: httpx.BaseTransport | None = None


class SiwcError(Exception):
    def __init__(self, code: str, detail: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


def _auth_base() -> str:
    return get_settings().chatgpt_auth_base.rstrip("/")


def _api_base() -> str:
    return get_settings().chatgpt_api_base.rstrip("/")


def _client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(transport=transport, timeout=timeout, follow_redirects=False)


def is_local(hostname: str | None) -> bool:
    return (hostname or "").lower() in LOOPBACK


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _claims(jwt: str) -> dict[str, Any]:
    try:
        payload = jwt.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


# --- sign-in ------------------------------------------------------------------------------------------------------


@dataclass
class Pending:
    user_id: uuid.UUID
    verifier: str
    nonce: str
    redirect_uri: str
    client_id: str | None
    return_to: str
    created: float


_pending: dict[str, Pending] = {}
_pending_lock = threading.Lock()


def start(user_id: uuid.UUID, port: int, return_to: str) -> str:
    """The authorize URL for the learner's browser. Contains no secret: state, nonce and the PKCE challenge only."""
    record = store.load(user_id)
    client_id = record.get("client_id")
    verifier = _b64url(secrets.token_bytes(48))
    state = _b64url(secrets.token_bytes(24))
    nonce = _b64url(secrets.token_bytes(24))
    redirect_uri = f"http://127.0.0.1:{port}{CALLBACK_PATH}"
    params = {
        "response_type": "code",
        "client_id": client_id or "dynamic_agent_client",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "resource": "https://api.openai.com/v1",
        "state": state,
        "nonce": nonce,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode("ascii")).digest()),
        "code_challenge_method": "S256",
        "ext_agent_host_id": store.host_id(),
    }
    if not client_id:
        params["agent_name_hint"] = APP_NAME
    now = time.monotonic()
    with _pending_lock:
        for key in [k for k, p in _pending.items() if now - p.created > PENDING_SECONDS]:
            del _pending[key]
        if len(_pending) >= 20:
            del _pending[min(_pending, key=lambda k: _pending[k].created)]
        _pending[state] = Pending(user_id, verifier, nonce, redirect_uri, client_id, return_to, now)
    return f"{_auth_base()}/api/accounts/authorize?{urlencode(params)}"


def _token_request(data: dict[str, str]) -> dict[str, Any]:
    try:
        with _client() as http:
            r = http.post(f"{_auth_base()}/api/accounts/oauth/token", data=data, headers={"Accept": "application/json"})
    except httpx.HTTPError as exc:
        raise SiwcError("unavailable") from exc
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code >= 500:
        raise SiwcError("unavailable")
    if r.status_code >= 400 or not isinstance(body, dict):
        raise SiwcError(str(body.get("error") or "token_error") if isinstance(body, dict) else "token_error")
    return body


def complete(params: dict[str, str]) -> tuple[uuid.UUID | None, str, str]:
    """Handle the callback: returns (user id, where to send the browser, outcome)."""
    with _pending_lock:
        pending = _pending.pop(params.get("state") or "", None)
    if pending is None or time.monotonic() - pending.created > PENDING_SECONDS:
        return None, "", "expired"
    if params.get("error"):
        return pending.user_id, pending.return_to, "declined" if params["error"] == "access_denied" else "error"
    issued = params.get("client_id") or pending.client_id
    if not issued or (pending.client_id and params.get("client_id") and params["client_id"] != pending.client_id):
        return pending.user_id, pending.return_to, "error"
    code = params.get("code")
    if not code:
        return pending.user_id, pending.return_to, "error"
    try:
        tokens = _token_request(
            {
                "grant_type": "authorization_code",
                "client_id": issued,
                "code": code,
                "code_verifier": pending.verifier,
                "redirect_uri": pending.redirect_uri,
                "resource": "https://api.openai.com/v1",
            }
        )
    except SiwcError:
        return pending.user_id, pending.return_to, "error"
    claims = _claims(str(tokens.get("id_token") or ""))
    aud = claims.get("aud")
    audiences = aud if isinstance(aud, list) else [aud]
    if (
        claims.get("iss") != _auth_base()
        or issued not in audiences
        or claims.get("nonce") != pending.nonce
        or float(claims.get("exp") or 0) < time.time()
        or not tokens.get("access_token")
    ):
        return pending.user_id, pending.return_to, "error"
    scopes = str(tokens.get("scope") or params.get("scope") or "").split()
    store.save(
        pending.user_id,
        {
            "client_id": issued,
            "issuer": claims.get("iss"),
            "subject": claims.get("sub"),
            "email": claims.get("email"),
            "name": claims.get("name"),
            "scopes": scopes,
            "id_token": tokens.get("id_token"),
            "access_token": tokens["access_token"],
            "refresh_token": tokens.get("refresh_token"),
            "expires_at": time.time() + float(tokens.get("expires_in") or 3600),
            "saved_at": time.time(),
        },
    )
    return pending.user_id, pending.return_to, "connected" if PLAN_SCOPE in scopes else "no_plan_usage"


# --- tokens -------------------------------------------------------------------------------------------------------

_refresh_locks: dict[uuid.UUID, threading.Lock] = {}


def _access_token(user_id: uuid.UUID) -> tuple[str, dict[str, Any]]:
    """A valid access token with plan usage, refreshed (one refresh at a time per learner) when it is about to end."""
    lock = _refresh_locks.setdefault(user_id, threading.Lock())
    with lock:
        record = store.load(user_id)
        if not record.get("access_token"):
            raise SiwcError("not_connected")
        if PLAN_SCOPE not in record.get("scopes", []):
            raise SiwcError("plan_usage_not_enabled")
        if float(record.get("expires_at") or 0) - time.time() > REFRESH_MARGIN_SECONDS:
            return record["access_token"], record
        if not record.get("refresh_token"):
            store.forget_tokens(user_id)
            raise SiwcError("signed_out")
        try:
            tokens = _token_request(
                {
                    "grant_type": "refresh_token",
                    "client_id": record["client_id"],
                    "refresh_token": record["refresh_token"],
                    "resource": "https://api.openai.com/v1",
                }
            )
        except SiwcError as exc:
            if exc.code in TERMINAL_REFRESH:
                store.forget_tokens(user_id)
                raise SiwcError("signed_out") from exc
            raise  # temporary: keep the credentials
        record.update(
            access_token=tokens["access_token"],
            refresh_token=tokens.get("refresh_token") or record["refresh_token"],
            expires_at=time.time() + float(tokens.get("expires_in") or 3600),
            saved_at=time.time(),
        )
        if tokens.get("scope"):
            record["scopes"] = str(tokens["scope"]).split()
        if tokens.get("id_token"):
            record["id_token"] = tokens["id_token"]
        store.save(user_id, record)
        return record["access_token"], record


def status(user_id: uuid.UUID) -> dict[str, Any]:
    record = store.load(user_id)
    scopes = record.get("scopes", [])
    return {
        "connected": bool(record.get("access_token")),
        "registered": bool(record.get("client_id")),
        "unreadable": bool(record.get("unreadable")),
        "email": record.get("email"),
        "name": record.get("name"),
        "scopes": scopes,
        "plan_usage": PLAN_SCOPE in scopes,
        "signed_in_at": record.get("saved_at"),
    }


# --- errors from api.openai.com -----------------------------------------------------------------------------------

_ERROR_CODES = {
    "subscription_sharing_usage_limit_exceeded": "usage_limit",
    "subscription_sharing_user_not_eligible": "not_eligible",
    "subscription_sharing_usage_unavailable": "unavailable",
    "subscription_sharing_user_unavailable": "unavailable",
    "subscription_sharing_unsupported_capability": "unsupported",
    "subscription_sharing_route_not_supported": "unsupported",
    "subscription_sharing_invalid_user": "auth_rejected",
    "chatpass_v2_scope_not_authorized": "plan_usage_not_enabled",
    "chatpass_v2_invalid_authorization_context": "plan_usage_not_enabled",
}


def _error_from(status_code: int, body: Any) -> SiwcError:
    code = None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            code = err.get("code")
    if code in _ERROR_CODES:
        return SiwcError(_ERROR_CODES[code])
    if status_code == 401:
        return SiwcError("auth_rejected")
    if status_code == 403:
        return SiwcError("not_allowed")
    if status_code == 429:
        return SiwcError("usage_limit")
    if status_code >= 500:
        return SiwcError("unavailable")
    return SiwcError("upstream_error", str(code) if code else None)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def list_models(user_id: uuid.UUID) -> list[dict[str, str]]:
    token, _ = _access_token(user_id)
    try:
        with _client() as http:
            r = http.get(f"{_api_base()}/models", headers=_headers(token))
    except httpx.HTTPError as exc:
        raise SiwcError("unavailable") from exc
    try:
        body = r.json()
    except ValueError:
        body = None
    if r.status_code != 200 or not isinstance(body, dict):
        raise _error_from(r.status_code, body)
    rows = body.get("models") if isinstance(body.get("models"), list) else body.get("data")
    out = []
    for m in rows if isinstance(rows, list) else []:
        if not isinstance(m, dict) or m.get("visibility", "list") != "list":
            continue
        slug = m.get("slug") or m.get("id")
        if isinstance(slug, str) and slug:
            out.append({"slug": slug, "display_name": str(m.get("display_name") or slug)})
    return out


# --- replies ------------------------------------------------------------------------------------------------------


def build_request(model: str, instructions: str, history: list[dict[str, str]]) -> dict[str, Any]:
    """The whole request body, from an allowlist. ``history`` is app-owned: role "user" or "assistant", text."""
    items: list[dict[str, Any]] = []
    for turn in history[-MAX_HISTORY:]:
        role = turn["role"]
        if role not in ("user", "assistant"):
            raise ValueError("only user and assistant turns are sent")
        kind = "input_text" if role == "user" else "output_text"
        items.append({"type": "message", "role": role, "content": [{"type": kind, "text": turn["text"]}]})
    body = {"model": model, "instructions": instructions, "input": items, "store": False, "stream": True}
    if tuple(body) != REQUEST_FIELDS:  # pragma: no cover - guards future edits
        raise RuntimeError("SIWC request fields must stay within the allowlist")
    return body


def _events(lines: Iterator[str]) -> Iterator[dict[str, Any]]:
    """Server-sent events: one JSON object per event (``data:`` lines joined), "[DONE]" ignored."""
    data: list[str] = []
    for line in lines:
        if line == "":
            if data:
                raw = "\n".join(data)
                data = []
                if raw.strip() == "[DONE]":
                    continue
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(event, dict):
                    yield event
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        try:
            event = json.loads("\n".join(data))
        except ValueError:
            return
        if isinstance(event, dict):
            yield event


@dataclass
class Reply:
    text: str
    model: str
    usage: dict[str, Any] | None


def reply(user_id: uuid.UUID, model: str, instructions: str, history: list[dict[str, str]]) -> Reply:
    """One streamed reply. Only ``response.completed`` is success; anything else raises with a clear code."""
    token, _ = _access_token(user_id)
    body = build_request(model, instructions, history)
    parts: list[str] = []
    try:
        with _client(get_settings().ai_timeout_seconds) as http:
            with http.stream("POST", f"{_api_base()}/responses", json=body, headers=_headers(token)) as r:
                if r.status_code != 200:
                    r.read()
                    try:
                        err_body = r.json()
                    except ValueError:
                        err_body = None
                    raise _error_from(r.status_code, err_body)
                for event in _events(r.iter_lines()):
                    kind = event.get("type")
                    if kind == "response.output_text.delta" and isinstance(event.get("delta"), str):
                        parts.append(event["delta"])
                    elif kind == "response.completed":
                        response = event.get("response") if isinstance(event.get("response"), dict) else {}
                        usage = response.get("usage") if isinstance(response.get("usage"), dict) else None
                        return Reply("".join(parts), str(response.get("model") or model), usage)
                    elif kind == "response.failed":
                        response = event.get("response") if isinstance(event.get("response"), dict) else {}
                        raise _error_from(200, response)
                    elif kind == "response.incomplete":
                        raise SiwcError("incomplete")
                    elif kind == "error":
                        raise _error_from(200, {"error": event.get("error") or event})
    except httpx.HTTPError as exc:
        raise SiwcError("interrupted") from exc
    raise SiwcError("interrupted")


# --- logs ---------------------------------------------------------------------------------------------------------


class RedactCallbackQuery(logging.Filter):
    """Keep the one-time authorization code of the sign-in callback out of the access log."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        path = args[2] if isinstance(args, tuple) and len(args) >= 3 else None
        if isinstance(args, tuple) and isinstance(path, str) and path.startswith(CALLBACK_PATH):
            record.args = (*args[:2], CALLBACK_PATH + "?[redacted]", *args[3:])
        return True


# --- signing out --------------------------------------------------------------------------------------------------


def disconnect(user_id: uuid.UUID) -> bool:
    """Revoke the refresh token at OpenAI (best effort) and delete the tokens here. Returns whether OpenAI confirmed."""
    record = store.load(user_id)
    revoked = False
    if record.get("refresh_token") and record.get("client_id"):
        try:
            with _client() as http:
                config = http.get(f"{_auth_base()}/.well-known/openid-configuration").json()
                endpoint = config.get("revocation_endpoint") if isinstance(config, dict) else None
                host = urlsplit(endpoint or "").hostname or ""
                if endpoint and (host == urlsplit(_auth_base()).hostname):
                    r = http.post(
                        endpoint,
                        data={
                            "token": record["refresh_token"],
                            "token_type_hint": "refresh_token",
                            "client_id": record["client_id"],
                        },
                    )
                    revoked = r.status_code == 200
        except (httpx.HTTPError, ValueError):
            revoked = False
    store.forget_tokens(user_id)
    return revoked
