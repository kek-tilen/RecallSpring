"""Sign in with ChatGPT, proof of concept (ai/siwc.py, docs/04 Gate 0). Owner session + CSRF, except the OAuth
callback, which is checked by its one-time state instead. Connector tokens cannot reach these routes.

Every request to OpenAI starts from the learner pressing a button; nothing runs in the background. Conversations
are saved (services/ai_conversations.py) and are not used for tutoring or grading."""

from __future__ import annotations

import time
import uuid
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..ai import siwc
from ..config import get_settings
from ..db import get_db
from ..deps import Ctx, WriteCtx, csrf_ctx, current_ctx, write_ctx
from ..errors import ApiError
from ..schemas import ChatGptConversationPatch, ChatGptMaterialIn, ChatGptMessageIn
from ..services import ai_conversations as conv_svc
from ..services import chat_material, visual_blocks
from ..services.events import audit

router = APIRouter(tags=["chatgpt"])

INSTRUCTIONS = (
    "You are ChatGPT, used from RecallSpring, a study app the learner runs on their own computer. You cannot see "
    "the learner's records here, only excerpts of files they choose for a conversation (when there are any). Answer "
    "clearly and briefly, in the language the learner writes in."
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


@router.get("/ai/chatgpt/conversations")
def conversations(ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Saved conversations (newest first), recently deleted ones and token usage. Readable while signed out."""
    return conv_svc.list_view(db, ctx.user)


@router.get("/ai/chatgpt/conversations/{conversation_id}")
def conversation(
    conversation_id: uuid.UUID, ctx: Ctx = Depends(current_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    return conv_svc.conversation_view(db, conv_svc.get(db, ctx.user, conversation_id))


@router.post("/ai/chatgpt/messages")
def send_message(
    payload: ChatGptMessageIn, ctx: WriteCtx = Depends(write_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Save the learner's message, then ask ChatGPT and wait for the whole reply, which is saved with the model and
    version that answered, the time it took and the token usage. A retry with the same Idempotency-Key never asks
    twice."""
    if (seen := conv_svc.find_request(db, ctx.user, ctx.idempotency_key)) is not None:
        return conv_svc.conversation_view(db, conv_svc.get(db, ctx.user, seen.conversation_id))
    state = siwc.status(ctx.user.id)
    if not state["connected"]:
        raise _api_error(siwc.SiwcError("not_connected"))
    if not state["plan_usage"]:
        raise _api_error(siwc.SiwcError("plan_usage_not_enabled"))
    conv, question = conv_svc.save_question(
        db, ctx.user, payload.conversation_id, payload.model, payload.message, ctx.idempotency_key
    )
    if payload.conversation_id is None and payload.source_ids:
        chat_material.set_chosen(db, ctx.user, conv, payload.source_ids, ctx.request_id)
    db.commit()  # saved before ChatGPT is asked
    messages = conv_svc._messages(db, conv.id)
    earlier = [m for m in messages if m.id != question.id]
    records, excerpts, how = chat_material.gather(db, conv, payload.message, earlier)
    question.context = records or None
    turns, _ = conv_svc.history(messages)
    db.commit()  # what is sent is recorded before the request; no transaction stays open while waiting
    parts = [INSTRUCTIONS]
    if payload.visuals:
        parts.append(visual_blocks.INSTRUCTIONS)
    if excerpts:
        parts.append(chat_material.instructions(excerpts, how))
    started = time.monotonic()
    try:
        result = siwc.reply(ctx.user.id, payload.model, "\n\n".join(parts), turns)
    except siwc.SiwcError as exc:
        conv_svc.save_failure(db, question, exc.code, int((time.monotonic() - started) * 1000))
        audit(
            db,
            actor_id=ctx.user.id,
            action="ai.chatgpt_message",
            target_type="ai_conversation",
            target_id=conv.id,
            details={"model": payload.model, "outcome": exc.code, "excerpts": len(records)},
            request_id=ctx.request_id,
        )
        db.commit()
        error = _api_error(exc)
        error.details = {"conversation_id": str(conv.id)}
        raise error from exc
    reply = conv_svc.save_reply(
        db,
        ctx.user,
        question,
        text=result.text,
        model=result.model,
        response_id=result.response_id,
        usage=result.usage,
        account=state.get("email") or state.get("name"),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    audit(
        db,
        actor_id=ctx.user.id,
        action="ai.chatgpt_message",
        target_type="ai_conversation",
        target_id=conv.id,
        details={
            "model": result.model,
            "outcome": "completed",
            "turns": len(turns),
            "usage": reply.usage,
            "visuals_allowed": payload.visuals,
            "visuals": [v["ok"] for v in visual_blocks.from_reply(result.text, refs=[r["ref"] for r in records])],
            "excerpts": len(records),
            "excerpts_chosen_by": how,
        },
        request_id=ctx.request_id,
    )
    db.commit()
    return conv_svc.conversation_view(db, conv)


@router.patch("/ai/chatgpt/conversations/{conversation_id}")
def rename_conversation(
    conversation_id: uuid.UUID,
    payload: ChatGptConversationPatch,
    ctx: Ctx = Depends(csrf_ctx),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    conv = conv_svc.rename(db, ctx.user, conversation_id, payload.title)
    db.commit()
    return conv_svc.conversation_view(db, conv)


@router.put("/ai/chatgpt/conversations/{conversation_id}/material")
def choose_material(
    conversation_id: uuid.UUID,
    payload: ChatGptMaterialIn,
    ctx: Ctx = Depends(csrf_ctx),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """The files whose matching excerpts are sent with this conversation's next messages (empty: none)."""
    conv = conv_svc.get(db, ctx.user, conversation_id, for_update=True)
    if conv.deleted_at is not None:
        raise ApiError(409, "conversation_deleted", "This conversation was deleted. Restore it to continue.")
    chat_material.set_chosen(db, ctx.user, conv, payload.source_ids, ctx.request_id)
    db.commit()
    return conv_svc.conversation_view(db, conv)


@router.delete("/ai/chatgpt/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: uuid.UUID, ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    """Soft delete (restorable for 30 days), after the learner confirmed it."""
    conv_svc.set_deleted(db, ctx.user, conversation_id, True, ctx.request_id)
    db.commit()
    return conv_svc.list_view(db, ctx.user)


@router.post("/ai/chatgpt/conversations/{conversation_id}/restore")
def restore_conversation(
    conversation_id: uuid.UUID, ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)
) -> dict[str, Any]:
    conv_svc.set_deleted(db, ctx.user, conversation_id, False, ctx.request_id)
    db.commit()
    return conv_svc.list_view(db, ctx.user)


@router.post("/ai/chatgpt/disconnect")
def disconnect(ctx: Ctx = Depends(csrf_ctx), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Sign out at OpenAI (best effort) and delete the tokens from this computer."""
    revoked = siwc.disconnect(ctx.user.id)
    audit(db, actor_id=ctx.user.id, action="ai.chatgpt_disconnected", details={"revoked_at_openai": revoked})
    db.commit()
    return {**siwc.status(ctx.user.id), "revoked": revoked}
