"""HTTP client for the RecallSpring connector API (``/api/v1/connector``) with friendly, secret-free errors."""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

DEFAULT_API_URL = "http://127.0.0.1:4318"


def default_token_file() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "RecallSpring" if base else Path.home() / ".config" / "recallspring"
    return root / "connector-token"


class ConnectorError(ToolError):
    """An anticipated failure; the message is shown to Claude and never contains tokens or learner text."""


class RecallSpringClient:
    def __init__(self, api_url: str, token: str, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.api_url = api_url.rstrip("/")
        self._http = httpx.AsyncClient(
            base_url=f"{self.api_url}/api/v1/connector",
            headers={"Authorization": f"Bearer {token}", "User-Agent": "recallspring-mcp"},
            timeout=httpx.Timeout(30.0, connect=5.0),
            transport=transport,
        )

    @classmethod
    def from_environment(cls) -> RecallSpringClient:
        api_url = os.environ.get("RS_API_URL", DEFAULT_API_URL)
        path = Path(os.environ.get("RS_CONNECTOR_TOKEN_FILE") or default_token_file())
        try:
            token = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ConnectorError(
                f"No connector token found at {path}. Create one with "
                "`recallspring connector-token --username <you>` (see docs/connector-setup.md)."
            ) from exc
        if not token:
            raise ConnectorError(f"The connector token file {path} is empty.")
        return cls(api_url, token)

    async def get(self, path: str, **params: Any) -> Any:
        clean = {k: v for k, v in params.items() if v is not None}
        return await self._send("GET", path, params=clean)

    async def post(self, path: str, payload: Any, idempotency_key: str | None = None) -> Any:
        headers = {"Idempotency-Key": idempotency_key or str(uuid.uuid4())}
        return await self._send("POST", path, json=payload, headers=headers)

    async def _send(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = await self._http.request(method, path, **kwargs)
        except httpx.TransportError as exc:
            raise ConnectorError(
                f"RecallSpring is not reachable at {self.api_url}. Start the RecallSpring API and try again."
            ) from exc
        if response.status_code >= 400:
            raise ConnectorError(_error_message(response))
        return response.json()

    async def aclose(self) -> None:
        await self._http.aclose()


def _error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = {}
    code = body.get("code", "error")
    message = body.get("message", "RecallSpring could not complete the request.")
    details = body.get("details") or {}
    reason = details.get("reason") if isinstance(details, dict) else None
    suffix = f" ({reason})" if reason else ""
    return f"[{response.status_code} {code}] {message}{suffix}"
