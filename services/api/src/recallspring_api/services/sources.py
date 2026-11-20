"""Source bookkeeping: creation with de-duplication and quota checks, views, grounding lookups and search."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..errors import ApiError
from ..ingest import jobs
from ..ingest.storage import commit_blob, storage_key
from ..models import ConceptSource, Source, SourceSection, User
from ..schemas import SectionOut, SourceOut
from .events import learning_event

PARSE_MESSAGES = {
    "no_extractable_text": "Text couldn't be extracted. Try a text-based PDF or paste the content.",
    "pdf_encrypted": "This PDF is password-protected. Remove the protection or paste the content.",
    "pdf_unreadable": "This PDF could not be read. It may be damaged; export it again or paste the content.",
    "too_many_pages": "This PDF has too many pages. Split it into smaller files.",
    "empty_document": "The document contains no text.",
    "unsupported_encoding": "The text file is not UTF-8. Save it as UTF-8 and upload it again.",
    "extraction_timeout": "Text extraction took too long. Try a smaller file or paste the content.",
    "extraction_crashed": "Text extraction failed unexpectedly. You can retry.",
}

UPLOAD_ERRORS = {
    "file_too_large": (413, "The file is larger than the upload limit."),
    "unsupported_file_type": (
        415,
        "Only PDF, Markdown (.md), plain text (.txt) and images (.png, .jpg, .webp) are supported.",
    ),
    "content_does_not_match_type": (415, "The file content does not match its extension."),
    "unsupported_encoding": (415, "The text file is not UTF-8. Save it as UTF-8 and upload it again."),
}


def upload_error(code: str) -> ApiError:
    status, message = UPLOAD_ERRORS[code]
    return ApiError(status, code, message)


def parse_message(source: Source) -> str | None:
    if source.kind == "image":
        return None
    if source.parse_state == "failed":
        return PARSE_MESSAGES.get(source.parse_error or "", "Text couldn't be extracted.")
    if source.parse_state == "needs_attention":
        pages = next((n.split(":", 1)[1] for n in source.parse_notes if n.startswith("pages_without_text:")), "")
        return f"Some pages have no extractable text (possibly scanned): {pages.replace(',', ', ')}."
    return None


def source_view(db: Session, source: Source) -> dict[str, Any]:
    count = db.scalar(
        select(func.count())
        .select_from(SourceSection)
        .where(SourceSection.source_id == source.id, SourceSection.source_version == source.version)
    )
    duplicate_course = db.scalar(select(Source.course_id).where(Source.id == source.duplicate_of_id))
    return SourceOut(
        id=source.id,
        course_id=source.course_id,
        filename=source.filename,
        kind=source.kind,
        mime_type=source.mime_type,
        byte_size=source.byte_size,
        sha256=source.sha256,
        origin=source.origin,
        category=source.category,
        duplicate_of_id=source.duplicate_of_id,
        duplicate_of_course_id=duplicate_course,
        parse_state=source.parse_state,  # type: ignore[arg-type]
        parse_error=source.parse_error,
        parse_message=parse_message(source),
        parse_notes=source.parse_notes,
        page_count=source.page_count,
        version=source.version,
        section_count=count or 0,
        uploaded_at=source.uploaded_at,
        parsed_at=source.parsed_at,
    ).model_dump(mode="json")


def section_view(section: SourceSection) -> dict[str, Any]:
    return SectionOut.model_validate(section, from_attributes=True).model_dump(mode="json")


def _library_bytes(db: Session, user_id: uuid.UUID) -> int:
    distinct = (
        select(Source.sha256, func.max(Source.byte_size).label("size"))
        .where(Source.user_id == user_id, Source.deleted_at.is_(None))
        .group_by(Source.sha256)
        .subquery()
    )
    return int(db.scalar(select(func.coalesce(func.sum(distinct.c.size), 0))) or 0)


def create_source(
    db: Session,
    *,
    user: User,
    course_id: uuid.UUID,
    tmp: Path,
    sha256: str,
    size: int,
    filename: str,
    kind: str,
    mime: str,
    origin: str,
    request_id: str,
    category: str = "material",
) -> Source:
    """Store the original, create the source row and queue extraction, all in the caller's transaction."""
    existing = db.scalar(
        select(Source)
        .where(Source.user_id == user.id, Source.sha256 == sha256, Source.deleted_at.is_(None))
        .order_by(Source.uploaded_at)
        .limit(1)
    )
    if existing is None and _library_bytes(db, user.id) + size > get_settings().max_library_bytes:
        tmp.unlink(missing_ok=True)
        raise ApiError(413, "library_full", "Your library has reached its storage limit.")
    key = storage_key(user.id, sha256)
    commit_blob(tmp, key)
    source = Source(
        user_id=user.id,
        course_id=course_id,
        filename=filename,
        kind=kind,
        mime_type=mime,
        byte_size=size,
        sha256=sha256,
        storage_key=key,
        origin=origin,
        category=category,
        duplicate_of_id=existing.id if existing else None,
        parse_state="pending",
    )
    if kind == "image":
        # No text extraction (no OCR): the image is kept as is and Claude looks at it on request (view_image).
        source.parse_state = "ready"
        source.parsed_at = clock.now()
        source.parse_notes = ["image"]
    db.add(source)
    db.flush()
    if kind != "image":
        jobs.enqueue(db, user_id=user.id, type=jobs.EXTRACT_SOURCE, payload={"source_id": str(source.id), "version": 1})
    learning_event(
        db,
        user_id=user.id,
        entity_type="source",
        entity_id=source.id,
        event_type="source.added",
        payload={
            "kind": kind,
            "category": category,
            "origin": origin,
            "bytes": size,
            "duplicate_of": str(existing.id) if existing else None,
        },
        request_id=request_id,
    )
    return source


def current_sections(db: Session, source: Source, offset: int, limit: int) -> tuple[list[SourceSection], int]:
    base = select(SourceSection).where(
        SourceSection.source_id == source.id, SourceSection.source_version == source.version
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(db.scalars(base.order_by(SourceSection.position).offset(offset).limit(limit)))
    return rows, total


def sections_in_course(
    db: Session, user_id: uuid.UUID, course_id: uuid.UUID, section_ids: list[uuid.UUID]
) -> list[SourceSection]:
    """Resolve section IDs for grounding; every ID must belong to the owner and to a live source of the course."""
    if not section_ids:
        return []
    rows = list(
        db.scalars(
            select(SourceSection)
            .join(Source, Source.id == SourceSection.source_id)
            .where(
                SourceSection.id.in_(section_ids),
                SourceSection.user_id == user_id,
                Source.course_id == course_id,
                Source.deleted_at.is_(None),
            )
        )
    )
    if len(rows) != len(set(section_ids)):
        raise ApiError(422, "unknown_source_refs", "Some source references do not exist in this course.")
    order = {sid: i for i, sid in enumerate(section_ids)}
    return sorted(rows, key=lambda s: order[s.id])


def parse_refs(refs: list[str]) -> list[uuid.UUID]:
    try:
        return [uuid.UUID(r) for r in refs]
    except ValueError as exc:
        raise ApiError(422, "unknown_source_refs", "Source references must be section IDs.") from exc


def sections_for_concepts(db: Session, user_id: uuid.UUID, concept_ids: list[uuid.UUID]) -> list[SourceSection]:
    return list(
        db.scalars(
            select(SourceSection)
            .join(ConceptSource, ConceptSource.section_id == SourceSection.id)
            .join(Source, Source.id == SourceSection.source_id)
            .where(
                ConceptSource.concept_id.in_(concept_ids),
                SourceSection.user_id == user_id,
                Source.deleted_at.is_(None),
            )
            .order_by(SourceSection.source_id, SourceSection.position)
            .distinct()
        )
    )


def search_sections(db: Session, user_id: uuid.UUID, query: str, course_id: uuid.UUID | None, limit: int):  # type: ignore[no-untyped-def]
    """Full-text search over current section versions. Language-neutral ('simple') because material can be in
    any language. Snippets use « » markers instead of HTML."""
    stmt = text(
        """
        SELECT s.id AS section_id, s.source_id, src.filename, s.citation_label,
               ts_headline('simple'::regconfig, s.text, q,
                           'StartSel=«,StopSel=»,MaxFragments=2,MaxWords=30,MinWords=8') AS snippet,
               ts_rank(s.tsv, q) AS rank
        FROM source_sections s
        JOIN sources src ON src.id = s.source_id AND src.version = s.source_version,
             websearch_to_tsquery('simple'::regconfig, :query) q
        WHERE s.user_id = :user_id AND src.deleted_at IS NULL
          AND (CAST(:course_id AS uuid) IS NULL OR src.course_id = CAST(:course_id AS uuid))
          AND s.tsv @@ q
        ORDER BY rank DESC, src.filename, s.position
        LIMIT :limit
        """
    )
    return (
        db.execute(stmt, {"query": query, "user_id": user_id, "course_id": course_id, "limit": limit}).mappings().all()
    )
