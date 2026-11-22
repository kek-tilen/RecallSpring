"""Saved conversations with ChatGPT (Settings → ChatGPT; docs/04 → Adapter `siwc`).

The learner's message is saved before ChatGPT is called. A reply is saved with what OpenAI reported about it: the
model and version that answered, its response id and token usage, plus when it arrived, how long it took and which
ChatGPT account was signed in. A failed request keeps the learner's message with the error code. Conversations stay
when the learner signs out of ChatGPT or out of RecallSpring; deleting one is a soft delete (restorable, audited).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import ApiError
from ..models import AiConversation, AiMessage, Course, User
from . import chat_material, visual_blocks
from .events import audit

PROVIDER = "chatgpt"
MAX_TITLE = 80
# What is sent again with every message: the newest turns up to these limits (older ones are left out and the
# conversation says so).
MAX_TURNS_SENT = 40
MAX_CHARS_SENT = 60_000
RESTORE_DAYS = 30


def _usage(raw: dict[str, Any] | None) -> dict[str, int] | None:
    """Only the token counts OpenAI reports (numbers), nothing else from the response."""
    if not isinstance(raw, dict):
        return None

    def num(value: Any) -> int | None:
        return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None

    inp = raw.get("input_tokens_details") if isinstance(raw.get("input_tokens_details"), dict) else {}
    out = raw.get("output_tokens_details") if isinstance(raw.get("output_tokens_details"), dict) else {}
    values = {
        "input_tokens": num(raw.get("input_tokens")),
        "cached_tokens": num(inp.get("cached_tokens")),
        "output_tokens": num(raw.get("output_tokens")),
        "reasoning_tokens": num(out.get("reasoning_tokens")),
        "total_tokens": num(raw.get("total_tokens")),
    }
    if values["total_tokens"] is None and values["input_tokens"] is not None and values["output_tokens"] is not None:
        values["total_tokens"] = values["input_tokens"] + values["output_tokens"]
    kept = {k: v for k, v in values.items() if v is not None}
    return kept or None


def combine_usage(raws: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    """Usage of all responses of one turn (with tools there is one per round), in OpenAI's shape."""
    parts = [u for u in (_usage(r) for r in raws) if u]
    if not parts:
        return None

    def total(key: str) -> int | None:
        values = [p[key] for p in parts if key in p]
        return sum(values) if values else None

    out: dict[str, Any] = {
        "input_tokens": total("input_tokens"),
        "output_tokens": total("output_tokens"),
        "total_tokens": total("total_tokens"),
        "input_tokens_details": {"cached_tokens": total("cached_tokens")},
        "output_tokens_details": {"reasoning_tokens": total("reasoning_tokens")},
    }
    return out


def message_view(m: AiMessage, refs: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """``refs``: the excerpts sent so far in the conversation (ref -> record); a reply's citations and visuals are
    resolved against them only."""
    visuals = visual_blocks.from_reply(m.text, refs=list(refs) if refs else None) if m.role == "assistant" else []
    cited = chat_material.citations(m.text, refs or {}) if m.role == "assistant" else {}
    for v in visuals:
        for ref in v.get("block", {}).get("source_refs", []):
            if refs and ref in refs and ref not in cited:
                cited[ref] = {k: refs[ref][k] for k in ("section_id", "source_id", "filename", "label")}
    return {
        "id": str(m.id),
        "position": m.position,
        "role": m.role,
        "text": m.text,
        "created_at": m.created_at.isoformat(),
        "completed_at": m.completed_at.isoformat() if m.completed_at else None,
        "model_requested": m.model_requested,
        "model": m.model,
        "response_id": m.response_id,
        "account": m.account,
        "usage": m.usage,
        "duration_ms": m.duration_ms,
        "error_code": m.error_code,
        # Checked again on every read, so a stricter check also applies to replies saved earlier.
        "visuals": visuals,
        "citations": cited,
        # On the learner's message: which excerpts of their chosen files were sent with it.
        "context": m.context or [] if m.role == "user" else [],
        # On the learner's message: what ChatGPT read or saved in RecallSpring while answering it.
        "tool_calls": m.tool_calls or [] if m.role == "user" else [],
        # On the learner's message: images pasted or dropped into it (image sources in the Library).
        "photo_ids": [str(p) for p in m.photo_ids or []] if m.role == "user" else [],
    }


def _messages(db: Session, conversation_id: uuid.UUID) -> list[AiMessage]:
    stmt = select(AiMessage).where(AiMessage.conversation_id == conversation_id).order_by(AiMessage.position)
    return list(db.scalars(stmt))


def history(messages: list[AiMessage]) -> tuple[list[dict[str, Any]], bool]:
    """The turns to send: user messages that got a reply (or the newest one) and the replies, newest first within
    the limits. Returns (turns, whether older turns were left out)."""
    usable = [m for m in messages if not (m.role == "user" and m.error_code)]
    turns: list[dict[str, str]] = []
    chars = 0
    for m in reversed(usable):
        if len(turns) >= MAX_TURNS_SENT or chars + len(m.text) > MAX_CHARS_SENT:
            break
        text = m.text
        if m.role == "user" and m.photo_ids:  # images go only with the newest message (chatgpt.py); say so here
            n = len(m.photo_ids)
            text += f"\n\n[{n} image{'s' if n > 1 else ''} attached to this message; shown when it was sent]"
        turns.append({"role": m.role, "text": text})
        chars += len(m.text)
    turns.reverse()
    while turns and turns[0]["role"] != "user":  # start with the learner's turn
        turns.pop(0)
    return turns, len(turns) < len(usable)


def _totals(rows: list[AiMessage]) -> dict[str, int]:
    replies = [m for m in rows if m.role == "assistant"]
    return {
        "replies": len(replies),
        "input_tokens": sum((m.usage or {}).get("input_tokens", 0) for m in replies),
        "output_tokens": sum((m.usage or {}).get("output_tokens", 0) for m in replies),
        "total_tokens": sum((m.usage or {}).get("total_tokens", 0) for m in replies),
    }


def conversation_view(db: Session, conv: AiConversation) -> dict[str, Any]:
    messages = _messages(db, conv.id)
    _, trimmed = history(messages)
    views = [message_view(m, chat_material.refs_for(messages, m.position)) for m in messages]
    course = db.get(Course, conv.course_id) if conv.course_id else None
    return {
        "id": str(conv.id),
        "title": conv.title,
        "course": {"id": str(course.id), "title": course.title}
        if course is not None and course.deleted_at is None
        else None,
        "created_at": conv.created_at.isoformat(),
        "updated_at": conv.updated_at.isoformat(),
        "deleted_at": conv.deleted_at.isoformat() if conv.deleted_at else None,
        "messages": views,
        "material": chat_material.sources_view(db, conv),
        "totals": _totals(messages),
        "older_turns_not_sent": trimmed,
    }


def list_view(db: Session, user: User) -> dict[str, Any]:
    """Conversations (newest first), recently deleted ones, and usage over the last day and 30 days."""
    convs = list(
        db.scalars(
            select(AiConversation)
            .where(AiConversation.user_id == user.id, AiConversation.provider == PROVIDER)
            .order_by(AiConversation.updated_at.desc())
        )
    )
    counts = dict(
        db.execute(
            select(AiMessage.conversation_id, func.count())
            .where(AiMessage.user_id == user.id, AiMessage.role == "assistant")
            .group_by(AiMessage.conversation_id)
        ).all()
    )
    now = clock.now()

    def summary(c: AiConversation) -> dict[str, Any]:
        return {
            "id": str(c.id),
            "title": c.title,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
            "deleted_at": c.deleted_at.isoformat() if c.deleted_at else None,
            "replies": counts.get(c.id, 0),
        }

    recent = list(
        db.scalars(
            select(AiMessage).where(
                AiMessage.user_id == user.id,
                AiMessage.role == "assistant",
                AiMessage.created_at >= now - timedelta(days=30),
            )
        )
    )
    return {
        "conversations": [summary(c) for c in convs if c.deleted_at is None],
        "deleted": [
            summary(c) for c in convs if c.deleted_at is not None and c.deleted_at >= now - timedelta(days=RESTORE_DAYS)
        ],
        "usage": {
            "last_24_hours": _totals([m for m in recent if m.created_at >= now - timedelta(days=1)]),
            "last_30_days": _totals(recent),
        },
    }


def get(db: Session, user: User, conversation_id: uuid.UUID, *, for_update: bool = False) -> AiConversation:
    stmt = select(AiConversation).where(AiConversation.id == conversation_id, AiConversation.user_id == user.id)
    if for_update:
        stmt = stmt.with_for_update()
    conv = db.scalar(stmt)
    if conv is None:
        raise ApiError(404, "not_found", "Conversation not found.")
    return conv


def find_request(db: Session, user: User, client_request_id: uuid.UUID) -> AiMessage | None:
    return db.scalar(
        select(AiMessage).where(AiMessage.user_id == user.id, AiMessage.client_request_id == client_request_id)
    )


def _title(text: str) -> str:
    line = " ".join(text.split())
    return line if len(line) <= MAX_TITLE else line[: MAX_TITLE - 1].rstrip() + "…"


def _next_position(db: Session, conversation_id: uuid.UUID) -> int:
    top = db.scalar(select(func.max(AiMessage.position)).where(AiMessage.conversation_id == conversation_id))
    return (top or 0) + 1


def save_question(
    db: Session,
    user: User,
    conversation_id: uuid.UUID | None,
    model: str,
    text: str,
    client_request_id: uuid.UUID,
    course_id: uuid.UUID | None = None,
    photo_ids: list[uuid.UUID] | None = None,
) -> tuple[AiConversation, AiMessage]:
    """Save the learner's message (a new conversation when none is given; ``course_id`` makes it a study
    conversation, checked by the caller). The caller commits before calling ChatGPT."""
    now = clock.now()
    if conversation_id is None:
        conv = AiConversation(
            user_id=user.id,
            provider=PROVIDER,
            title=_title(text),
            course_id=course_id,
            created_at=now,
            updated_at=now,
        )
        db.add(conv)
        db.flush()
    else:
        conv = get(db, user, conversation_id, for_update=True)
        if conv.deleted_at is not None:
            raise ApiError(409, "conversation_deleted", "This conversation was deleted. Restore it to continue.")
        conv.updated_at = now
    msg = AiMessage(
        user_id=user.id,
        conversation_id=conv.id,
        position=_next_position(db, conv.id),
        role="user",
        text=text,
        client_request_id=client_request_id,
        model_requested=model,
        photo_ids=[str(p) for p in photo_ids or []],
        created_at=now,
    )
    db.add(msg)
    db.flush()
    return conv, msg


def save_reply(
    db: Session,
    user: User,
    question: AiMessage,
    *,
    text: str,
    model: str,
    response_id: str | None,
    usage: dict[str, Any] | None,
    account: str | None,
    duration_ms: int,
) -> AiMessage:
    conv = get(db, user, question.conversation_id, for_update=True)
    now = clock.now()
    reply = AiMessage(
        user_id=user.id,
        conversation_id=conv.id,
        position=_next_position(db, conv.id),
        role="assistant",
        text=text,
        model_requested=question.model_requested,
        model=model,
        response_id=response_id,
        account=account,
        usage=_usage(usage),
        duration_ms=duration_ms,
        created_at=now,
        completed_at=now,
    )
    question.completed_at = now
    conv.updated_at = now
    db.add(reply)
    db.flush()
    return reply


def save_failure(db: Session, question: AiMessage, code: str, duration_ms: int) -> None:
    question.error_code = code[:60]
    question.duration_ms = duration_ms
    question.completed_at = clock.now()


def rename(db: Session, user: User, conversation_id: uuid.UUID, title: str) -> AiConversation:
    conv = get(db, user, conversation_id, for_update=True)
    clean = " ".join(title.split())
    if not clean:
        raise ApiError(422, "title_required", "Give the conversation a name.")
    conv.title = clean[:200]
    return conv


def set_deleted(db: Session, user: User, conversation_id: uuid.UUID, deleted: bool, request_id: str | None) -> None:
    conv = get(db, user, conversation_id, for_update=True)
    if (conv.deleted_at is not None) == deleted:
        return
    if not deleted and conv.deleted_at is not None and conv.deleted_at < clock.now() - timedelta(days=RESTORE_DAYS):
        raise ApiError(409, "restore_period_over", f"Deleted conversations can be restored for {RESTORE_DAYS} days.")
    conv.deleted_at = clock.now() if deleted else None
    audit(
        db,
        actor_id=user.id,
        action="ai.chatgpt_conversation_deleted" if deleted else "ai.chatgpt_conversation_restored",
        target_type="ai_conversation",
        target_id=conv.id,
        request_id=request_id,
    )
