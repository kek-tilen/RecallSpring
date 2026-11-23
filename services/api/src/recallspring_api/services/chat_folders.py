"""Chat folders (ADR-012 §4): the learner files Chat conversations in folders of their own.

- Any number of top-level folders, each with any number of subfolders; nothing deeper (refused here, not only in
  the page). A conversation is in at most one folder (``ai_conversations.folder_id``).
- A folder has a name, an icon from a fixed set (``ICONS``; only folders have icons), an optional colour (``#rrggbb``)
  and an optional course link. Sorted alphabetically, pinned folders first.
- A new conversation about a course goes into that course's folder only when exactly one folder is linked to it.
- Deleting a folder never deletes conversations: after the learner confirmed it, its conversations move to the
  parent folder (or to "No folder") and its subfolders move up to the top level. The folder itself is soft-deleted
  and the move is audited with the IDs, so it can be put back by hand.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import clock
from ..errors import ApiError
from ..models import AiChatFolder, AiConversation, Course, User
from .events import audit
from .ownership import owned

# Agreed with the owner 2026-11-23 (mockup in chat); the page draws its own SVG for each name.
ICONS = (
    "folder",
    "book",
    "school",
    "flask",
    "function",
    "code",
    "shield",
    "globe",
    "language",
    "palette",
    "scale",
    "heart",
    "bulb",
    "calendar",
    "star",
    "chat",
)
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_NAME = 60
MAX_FOLDERS = 200


def _clean_name(name: str) -> str:
    clean = " ".join(name.split())
    if not clean:
        raise ApiError(422, "name_required", "Give the folder a name.")
    return clean[:MAX_NAME]


def _check_icon(icon: str) -> str:
    if icon not in ICONS:
        raise ApiError(422, "unknown_icon", "Pick one of the folder icons.", {"icons": list(ICONS)})
    return icon


def _check_color(color: str | None) -> str | None:
    if color is None or color == "":
        return None
    if not COLOR.match(color):
        raise ApiError(422, "invalid_color", "A colour is written as #rrggbb.")
    return color.lower()


def get(db: Session, user: User, folder_id: uuid.UUID, *, for_update: bool = False) -> AiChatFolder:
    stmt = select(AiChatFolder).where(
        AiChatFolder.id == folder_id, AiChatFolder.user_id == user.id, AiChatFolder.deleted_at.is_(None)
    )
    if for_update:
        stmt = stmt.with_for_update()
    folder = db.scalar(stmt)
    if folder is None:
        raise ApiError(404, "folder_not_found", "Folder not found.")
    return folder


def _children(db: Session, folder_id: uuid.UUID) -> list[AiChatFolder]:
    return list(
        db.scalars(select(AiChatFolder).where(AiChatFolder.parent_id == folder_id, AiChatFolder.deleted_at.is_(None)))
    )


def _check_parent(db: Session, user: User, parent_id: uuid.UUID | None, moving: AiChatFolder | None = None) -> None:
    """A parent must be a top-level folder of the learner; a folder with subfolders cannot become a subfolder."""
    if parent_id is None:
        return
    parent = get(db, user, parent_id)
    if parent.parent_id is not None:
        raise ApiError(422, "folder_too_deep", "Folders in Chat have one level of subfolders, no deeper.")
    if moving is not None:
        if parent.id == moving.id:
            raise ApiError(422, "folder_too_deep", "A folder cannot be inside itself.")
        if _children(db, moving.id):
            raise ApiError(
                422, "folder_too_deep", "This folder has subfolders, so it stays at the top level (one level only)."
            )


def _course(db: Session, user: User, course_id: uuid.UUID | None) -> uuid.UUID | None:
    if course_id is None:
        return None
    owned(db, Course, course_id, user.id)
    return course_id


def create(db: Session, user: User, data: dict[str, Any], request_id: str | None) -> AiChatFolder:
    count = db.scalar(
        select(func.count())
        .select_from(AiChatFolder)
        .where(AiChatFolder.user_id == user.id, AiChatFolder.deleted_at.is_(None))
    )
    if (count or 0) >= MAX_FOLDERS:
        raise ApiError(422, "too_many_folders", f"Chat keeps at most {MAX_FOLDERS} folders.")
    parent_id = data.get("parent_id")
    _check_parent(db, user, parent_id)
    folder = AiChatFolder(
        user_id=user.id,
        parent_id=parent_id,
        name=_clean_name(data["name"]),
        icon=_check_icon(data.get("icon") or "folder"),
        color=_check_color(data.get("color")),
        course_id=_course(db, user, data.get("course_id")),
        pinned=bool(data.get("pinned")),
    )
    db.add(folder)
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="chat_folder.created",
        target_type="ai_chat_folder",
        target_id=folder.id,
        details={"subfolder": parent_id is not None},
        request_id=request_id,
    )
    return folder


def change(db: Session, user: User, folder_id: uuid.UUID, data: dict[str, Any], request_id: str | None) -> AiChatFolder:
    """``data`` holds only the fields the learner sent (``parent_id`` / ``course_id`` / ``color`` may be null)."""
    folder = get(db, user, folder_id, for_update=True)
    if "name" in data and data["name"] is not None:
        folder.name = _clean_name(data["name"])
    if "icon" in data and data["icon"] is not None:
        folder.icon = _check_icon(data["icon"])
    if "color" in data:
        folder.color = _check_color(data["color"])
    if "course_id" in data:
        folder.course_id = _course(db, user, data["course_id"])
    if "pinned" in data and data["pinned"] is not None:
        folder.pinned = bool(data["pinned"])
    if "parent_id" in data and data["parent_id"] != folder.parent_id:
        _check_parent(db, user, data["parent_id"], folder)
        folder.parent_id = data["parent_id"]
    folder.updated_at = clock.now()
    audit(
        db,
        actor_id=user.id,
        action="chat_folder.updated",
        target_type="ai_chat_folder",
        target_id=folder.id,
        details={"fields": sorted(data)},
        request_id=request_id,
    )
    return folder


def delete(db: Session, user: User, folder_id: uuid.UUID, request_id: str | None) -> None:
    """Soft delete after the learner confirmed it; nothing inside is deleted (see the module docstring)."""
    folder = get(db, user, folder_id, for_update=True)
    moved = list(
        db.scalars(
            select(AiConversation.id).where(AiConversation.user_id == user.id, AiConversation.folder_id == folder.id)
        )
    )
    db.execute(
        update(AiConversation)
        .where(AiConversation.user_id == user.id, AiConversation.folder_id == folder.id)
        .values(folder_id=folder.parent_id, updated_at=AiConversation.updated_at)  # filing is not activity
    )
    lifted = [f.id for f in _children(db, folder.id)]
    if lifted:
        db.execute(update(AiChatFolder).where(AiChatFolder.id.in_(lifted)).values(parent_id=None))
    folder.deleted_at = clock.now()
    audit(
        db,
        actor_id=user.id,
        action="chat_folder.deleted",
        target_type="ai_chat_folder",
        target_id=folder.id,
        details={
            "conversations_moved_to": str(folder.parent_id) if folder.parent_id else None,
            "conversation_ids": [str(c) for c in moved],
            "subfolders_moved_to_top": [str(f) for f in lifted],
        },
        request_id=request_id,
    )


def file_conversation(
    db: Session, user: User, conversation_id: uuid.UUID, folder_id: uuid.UUID | None, request_id: str | None
) -> AiConversation:
    """Move to…: a folder of the learner, or None for "No folder". Filing is not activity: the conversation keeps
    its place in the list (``updated_at`` stays)."""
    conv = db.scalar(
        select(AiConversation)
        .where(AiConversation.id == conversation_id, AiConversation.user_id == user.id)
        .with_for_update()
    )
    if conv is None:
        raise ApiError(404, "not_found", "Conversation not found.")
    if folder_id is not None:
        get(db, user, folder_id)
    if conv.folder_id != folder_id:
        db.execute(
            update(AiConversation)
            .where(AiConversation.id == conv.id)
            .values(folder_id=folder_id, updated_at=AiConversation.updated_at)
        )
        db.refresh(conv)
        audit(
            db,
            actor_id=user.id,
            action="ai.chatgpt_conversation_moved",
            target_type="ai_conversation",
            target_id=conv.id,
            details={"folder_id": str(folder_id) if folder_id else None},
            request_id=request_id,
        )
    return conv


def folder_for_course(db: Session, user: User, course_id: uuid.UUID | None) -> uuid.UUID | None:
    """The folder a new conversation about ``course_id`` goes in: only when exactly one folder is linked to it."""
    if course_id is None:
        return None
    linked = list(
        db.scalars(
            select(AiChatFolder.id).where(
                AiChatFolder.user_id == user.id,
                AiChatFolder.course_id == course_id,
                AiChatFolder.deleted_at.is_(None),
            )
        )
    )
    return linked[0] if len(linked) == 1 else None


def list_view(db: Session, user: User, counts: dict[uuid.UUID, int]) -> list[dict[str, Any]]:
    """Folders in the order the page shows them: pinned first, then by name (subfolders under their parent).
    ``counts``: conversations directly in each folder."""
    folders = list(
        db.scalars(select(AiChatFolder).where(AiChatFolder.user_id == user.id, AiChatFolder.deleted_at.is_(None)))
    )
    courses = {
        c.id: c.title
        for c in db.scalars(
            select(Course).where(
                Course.id.in_({f.course_id for f in folders if f.course_id}), Course.deleted_at.is_(None)
            )
        )
    }

    def key(f: AiChatFolder) -> tuple[bool, str, str]:
        return (not f.pinned, f.name.casefold(), str(f.id))

    out: list[dict[str, Any]] = []
    tops = sorted((f for f in folders if f.parent_id is None), key=key)
    for top in tops:
        kids = sorted((f for f in folders if f.parent_id == top.id), key=key)
        for f in [top, *kids]:
            out.append(
                {
                    "id": str(f.id),
                    "parent_id": str(f.parent_id) if f.parent_id else None,
                    "name": f.name,
                    "icon": f.icon,
                    "color": f.color,
                    "course": {"id": str(f.course_id), "title": courses[f.course_id]}
                    if f.course_id in courses
                    else None,
                    "pinned": f.pinned,
                    "conversations": counts.get(f.id, 0),
                }
            )
    return out
