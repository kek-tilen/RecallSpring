"""References from a note to files in the learner's Library.

A note links a file with Markdown: ``[name](source:<id>)`` for any file, ``![name](source:<id>)`` to show a picture.
The body stays the learner's own text; RecallSpring only resolves the IDs (owner-scoped, deleted files reported as
missing without revealing anything about IDs that are not the learner's).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Note, Source

REF = re.compile(r"\]\(source:([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\)")
MAX_REFS = 100


def ref_ids(body: str) -> list[uuid.UUID]:
    """The referenced file IDs in order of first appearance (at most MAX_REFS)."""
    seen: dict[uuid.UUID, None] = {}
    for m in REF.finditer(body):
        seen.setdefault(uuid.UUID(m.group(1)), None)
        if len(seen) >= MAX_REFS:
            break
    return list(seen)


def references(db: Session, user_id: uuid.UUID, notes: Iterable[Note]) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """For each note, its referenced files: ``{id, filename, kind, course_id, missing}``, one query for all notes."""
    wanted = {n.id: ref_ids(n.body) for n in notes}
    ids = {i for refs in wanted.values() for i in refs}
    found: dict[uuid.UUID, Source] = {}
    if ids:
        rows = db.scalars(
            select(Source).where(Source.id.in_(ids), Source.user_id == user_id, Source.deleted_at.is_(None))
        )
        found = {s.id: s for s in rows}

    def view(i: uuid.UUID) -> dict[str, Any]:
        s = found.get(i)
        if s is None:
            return {"id": str(i), "filename": None, "kind": None, "course_id": None, "missing": True}
        return {"id": str(i), "filename": s.filename, "kind": s.kind, "course_id": str(s.course_id), "missing": False}

    return {note_id: [view(i) for i in refs] for note_id, refs in wanted.items()}
