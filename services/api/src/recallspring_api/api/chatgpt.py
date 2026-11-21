"""Sign in with ChatGPT, proof of concept (ai/siwc.py, docs/04 Gate 0). Owner session + CSRF, except the OAuth
callback, which is checked by its one-time state instead. Connector tokens cannot reach these routes.

Every request to OpenAI starts from the learner pressing a button; nothing runs in the background. The connection
test is not saved and is not used for tutoring or grading."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..ai import siwc
from ..config import get_settings
from ..db import get_db
from ..deps import Ctx, csrf_ctx, current_ctx
from ..errors import ApiError
from ..schemas import ChatGptTestIn
from ..services.events import audit

router = APIRouter(tags=["chatgpt"])

TEST_INSTRUCTIONS = (
    "You are answering a connection test from RecallSpring, a study app the user runs on their own computer. "
    "Answer briefly and in the language the user writes in."
)
MESSAGES = {
    "not_connected": (409, "Sign in with ChatGPT first."),
    "plan_usage_not_enabled": (
        409,
        "This sign-in does not allow RecallSpring to use your ChatGPT plan. Sign in again and allow plan usage.",
    ),
    "signed_out": (409, "Your ChatGPT sign-in has ended. Sign in again."),
    "auth_rejected": (409, "ChatGPT did not accept this sign-in. Sign in again if it keeps happening."),
    "not_eligible": (403, "This ChatGPT account can't use its plan in other apps (Plus or Pro is needed)."),
    "not_allowed": (403, "ChatGPT refused the request for this account or region."),
    "usage_limit": (
        429,
        "You have reached your ChatGPT plan's usage limit (see chatgpt.com/settings/usage). RecallSpring never "
        "switches to paid API usage; try again when your limit resets.",
    ),
    "unavailable": (503, "ChatGPT is not available right now. Try again in a few minutes."),
    "unsupported": (422, "ChatGPT does not support this request through Sign in with ChatGPT."),
    "incomplete": (502, "ChatGPT stopped before the reply was complete. Nothing was saved."),
    "interrupted": (502, "The reply was interrupted. Nothing was saved."),
    "upstream_error": (502, "ChatGPT returned an error."),
}


def _api_error(exc: siwc.SiwcError) -> ApiError:
    status, message = MESSAGES.get(exc.code, MESSAGES["upstream_error"])
    return ApiError(status, f"chatgpt_{exc.code}", message)


def _availability(request: Request) -> str | None:
    if not get_settings().chatgpt_signin_enabled:
        return "disabled"
    if not siwc.is_local(request.url.hostname):
        return "not_local"
    return None


def _safe_origin(origin: str) -> str:
    """Only send the browser back to RecallSpring on this computer."""
    parts = urlsplit(origin)
    return origin if parts.scheme in ("http", "https") and siwc.is_local(parts.hostname) else ""


@router.get("/ai/chatgpt")
def chatgpt_status(request: Request, ctx: Ctx = Depends(current_ctx)) -> dict[str, Any]:
    return {**siwc.status(ctx.user.id), "unavailable_reason": _availability(request)}


@router.post("/ai/chatgpt/connect")
def connect(request: Request, ctx: Ctx = Depends(csrf_ctx)) -> dict[str, str]:
    """The ChatGPT sign-in page to open. It returns to http://127.0.0.1:<this port>/api/v1/ai/chatgpt/callback."""
    reason = _availability(request)
    if reason == "disabled":
        raise ApiError(409, "chatgpt_disabled", "Sign in with ChatGPT is turned off (RS_CHATGPT_SIGNIN_ENABLED).")
    if reason == "not_local":
        raise ApiError(
            409,
            "chatgpt_not_local",
            "Sign in with ChatGPT works while RecallSpring runs on your own computer: open it at http://127.0.0.1.",
        )
    port = request.url.port or (443 if request.url.scheme == "https" else 80)
    origin = f"{request.url.scheme}://{request.url.netloc}"
    return {"authorize_url": siwc.start(ctx.user.id, port, origin)}


@router.get("/ai/chatgpt/callback", include_in_schema=False)
def callback(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    """Where ChatGPT sends the browser back. No session cookie is needed (the page may be on localhost while this is
    127.0.0.1): the one-time state ties it to the sign-in the learner started."""
    user_id, return_to, outcome = siwc.complete(dict(request.query_params))
    if user_id is not None:
        details: dict[str, Any] = {"outcome": outcome}
        if outcome in ("connected", "no_plan_usage"):
            details["scopes"] = siwc.status(user_id)["scopes"]
        audit(db, actor_id=user_id, action="ai.chatgpt_sign_in", details=details)
        db.commit()
    return RedirectResponse(f"{_safe_origin(return_to)}/settings?chatgpt={outcome}#chatgpt", status_code=303)


@router.get("/ai/chatgpt/models")
def models(ctx: Ctx = Depends(current_ctx)) -> list[dict[str, str]]:
    try:
        return siwc.list_models(ctx.user.id)
    except siwc.SiwcError as exc:
        raise _api_error(exc) from exc


@router.post("/ai/chatgpt/test")
def test_message(payload: ChatGptTestIn, ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Send one message (with the earlier turns of this test) and wait for the whole reply. Not saved."""
    if sum(len(t.text) for t in payload.history) + len(payload.message) > 40_000:
        raise ApiError(422, "chatgpt_test_too_long", "Clear the test conversation and start again.")
    history = [t.model_dump() for t in payload.history] + [{"role": "user", "text": payload.message}]
    try:
        result = siwc.reply(ctx.user.id, payload.model, TEST_INSTRUCTIONS, history)
    except siwc.SiwcError as exc:
        audit(db, actor_id=ctx.user.id, action="ai.chatgpt_test", details={"model": payload.model, "outcome": exc.code})
        db.commit()
        raise _api_error(exc) from exc
    audit(
        db,
        actor_id=ctx.user.id,
        action="ai.chatgpt_test",
        details={"model": result.model, "outcome": "completed", "turns": len(history)},
    )
    db.commit()
    return {"reply": result.text, "model": result.model, "usage": result.usage}


@router.post("/ai/chatgpt/disconnect")
def disconnect(ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Sign out at OpenAI (best effort) and delete the tokens from this computer."""
    revoked = siwc.disconnect(ctx.user.id)
    audit(db, actor_id=ctx.user.id, action="ai.chatgpt_disconnected", details={"revoked_at_openai": revoked})
    db.commit()
    return {**siwc.status(ctx.user.id), "revoked": revoked}
