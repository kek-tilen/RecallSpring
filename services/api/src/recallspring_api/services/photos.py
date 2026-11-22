"""Photos the learner adds to an answer (work solved on paper) or pastes into a Chat message.

A photo is first saved as an ordinary image in the course Library (answers: folder "Answer photos", category
notes), so it is backed up, can be opened later and is never lost if a model call fails. The answer or message only
keeps the ids (``photo_ids``). Assistants look at them when they grade or reply: Claude and Codex with view_image,
ChatGPT in Chat as images sent with the request. Photo content is the learner's work, never instructions.
"""

from __future__ import annotations

import base64
import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..errors import ApiError
from ..ingest import visuals
from ..ingest.storage import blob_path
from ..models import Source

log = logging.getLogger("recallspring.photos")

MAX_PHOTOS = 4
MODEL_FORMATS = {"image/png", "image/jpeg", "image/gif", "image/webp"}
SEND_AS_IS = 4_500_000  # bytes; a larger or unusual photo gets a smaller copy from the isolated render process


def checked(db: Session, user_id: uuid.UUID, ids: list[uuid.UUID], course_id: uuid.UUID | None) -> list[uuid.UUID]:
    """The ids in order without repeats, after checking each is the learner's own image (in ``course_id``)."""
    unique = list(dict.fromkeys(ids))
    if len(unique) > MAX_PHOTOS:
        raise ApiError(422, "too_many_photos", f"Add at most {MAX_PHOTOS} photos.")
    if not unique:
        return []
    rows = {
        s.id: s
        for s in db.scalars(
            select(Source).where(Source.id.in_(unique), Source.user_id == user_id, Source.deleted_at.is_(None))
        )
    }
    for pid in unique:
        source = rows.get(pid)
        if source is None or source.kind != "image":
            raise ApiError(422, "photo_invalid", "A photo could not be found. Add it again.")
        if course_id is not None and source.course_id != course_id:
            raise ApiError(422, "photo_other_course", "A photo belongs to another course. Add it again here.")
    return unique


def views(db: Session, ids: list[Any]) -> list[dict[str, Any]]:
    """[{id, filename, available}] for the web app and the assistants (deleted photos say so)."""
    if not ids:
        return []
    wanted = [uuid.UUID(str(i)) for i in ids]
    rows = {s.id: s for s in db.scalars(select(Source).where(Source.id.in_(wanted)))}
    out = []
    for pid in wanted:
        s = rows.get(pid)
        out.append(
            {
                "id": str(pid),
                "filename": s.filename if s else None,
                "available": bool(s and s.deleted_at is None),
            }
        )
    return out


def image_inputs(db: Session, user_id: uuid.UUID, ids: list[Any]) -> tuple[list[dict[str, Any]], int]:
    """Responses API ``input_image`` parts (data URLs) for the photos that can be shown; (parts, left out)."""
    parts: list[dict[str, Any]] = []
    left_out = 0
    settings = get_settings()
    for view in views(db, ids):
        source = db.get(Source, uuid.UUID(view["id"])) if view["available"] else None
        path = blob_path(source.storage_key) if source and source.user_id == user_id else None
        if source is None or path is None or not path.is_file():
            left_out += 1
            continue
        mime, data = source.mime_type, b""
        if source.mime_type in MODEL_FORMATS and source.byte_size <= SEND_AS_IS:
            data = path.read_bytes()
        else:
            try:
                result = visuals.run(
                    "image",
                    path,
                    0,
                    0,
                    isolation=settings.extraction_isolation,
                    timeout=settings.extraction_timeout_seconds,
                )
            except visuals.VisualFailure as exc:
                log.warning("photo %s could not be prepared: %s", source.id, exc.code)
                result = None
            if result is None or not result.images:
                left_out += 1
                continue
            mime, data = result.images[0].mime, result.images[0].data
        url = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        parts.append({"type": "input_image", "image_url": url})
    return parts, left_out
