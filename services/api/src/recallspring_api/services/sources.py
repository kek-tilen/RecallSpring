"""Source bookkeeping: creation with de-duplication and quota checks, views, grounding lookups and search."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..errors import ApiError
from ..ingest import jobs, renderer
from ..ingest.storage import ALLOWED_EXTENSIONS, TEXT_KINDS, commit_blob, storage_key
from ..models import ConceptSource, Source, SourceSection, User
from ..schemas import SectionOut, SourceOut
from .events import learning_event

PARSE_MESSAGES = {
    "no_extractable_text": (
        "No text could be extracted (scanned?). Claude can still look at the pages on request, or paste the content."
    ),
    "pdf_encrypted": "This PDF is password-protected. Remove the protection or paste the content.",
    "pdf_unreadable": "This PDF could not be read. It may be damaged; export it again or paste the content.",
    "too_many_pages": "This file has too many pages, slides or sheets. Split it into smaller files.",
    "office_unreadable": "This file could not be read. It may be damaged; save it again in Office or export a PDF.",
    "document_too_large": "This file is too large to read safely. Split it or export a PDF.",
    "unsafe_document": "This file contains XML features RecallSpring never reads (DTD or entities), so it was skipped.",
    "empty_document": "The document contains no text.",
    "unsupported_encoding": "The text file is not UTF-8. Save it as UTF-8 and upload it again.",
    "csv_unreadable": "This CSV file could not be read (a broken quote or a very long cell). Save it again.",
    "no_subtitle_cues": "No subtitle cues were found. Is it an .srt or .vtt file with timings?",
    "notebook_unreadable": "This notebook could not be read. Open it in Jupyter, save it again and retry.",
    "extraction_timeout": "Text extraction took too long. Try a smaller file or paste the content.",
    "extraction_crashed": "Text extraction failed unexpectedly. You can retry.",
}

# Per kind, where the generic message would point to the wrong fix.
KIND_PARSE_MESSAGES = {
    ("no_extractable_text", "docx"): (
        "This document has no text or pictures RecallSpring can read. Export it as PDF: Claude can look at its pages."
    ),
    ("no_extractable_text", "pptx"): (
        "These slides have no text or pictures RecallSpring can read. Export them as PDF: Claude can look at whole "
        "slides then."
    ),
    ("no_extractable_text", "xlsx"): "This spreadsheet has no visible cells with values.",
    ("no_extractable_text", "odt"): (
        "This document has no text or pictures RecallSpring can read. Export it as PDF: Claude can look at its pages."
    ),
    ("no_extractable_text", "odp"): (
        "These slides have no text or pictures RecallSpring can read. Export them as PDF: Claude can look at whole "
        "slides then."
    ),
    ("no_extractable_text", "ods"): "This spreadsheet has no visible cells with values.",
}

SUPPORTED_FILES = (
    "PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), OpenDocument (.odt, .odp, .ods), Markdown (.md), "
    "plain text (.txt), CSV/TSV, subtitles (.srt, .vtt), Jupyter notebooks (.ipynb), LaTeX (.tex), source code "
    "(.py, .java, .c, .js, .sql and more) and images (.png, .jpg, .webp)"
)

UPLOAD_ERRORS = {
    "file_too_large": (413, "The file is larger than the upload limit."),
    "unsupported_file_type": (415, f"Supported files: {SUPPORTED_FILES}."),
    "office_format_unsupported": (
        415,
        "This Office format isn't supported (old .doc/.ppt/.xls, macro-enabled or template files). "
        "Open it and save it as .docx, .pptx or .xlsx, or export a PDF.",
    ),
    "office_protected": (
        415,
        "This file is password-protected or in an old format. Remove the password, or save it as .docx, "
        ".pptx, .xlsx or OpenDocument (.odt, .odp, .ods), then upload it again.",
    ),
    "office_unreadable": (
        415,
        "This file could not be opened as a Word, PowerPoint, Excel or OpenDocument file. Save it again and retry.",
    ),
    "document_too_large": (413, "This file has too many parts to read safely. Split it or export a PDF."),
    "content_does_not_match_type": (415, "The file content does not match its extension."),
    "unsupported_encoding": (415, "The text file is not UTF-8. Save it as UTF-8 and upload it again."),
}


def upload_error(code: str) -> ApiError:
    status, message = UPLOAD_ERRORS[code]
    return ApiError(status, code, message)


def megabytes(n: int) -> str:
    return f"{n / 1024**3:g} GB" if n >= 1024**3 else f"{round(n / 1024**2)} MB"


def file_too_large(filename: str, limit: int) -> ApiError:
    return ApiError(
        413,
        "file_too_large",
        f"{filename} is larger than {megabytes(limit)}, the limit for this type of file. Split it, or compress a PDF "
        "(scans and pictures make files large; the text stays small).",
        {"limit_bytes": limit},
    )


def upload_limits(db: Session, user: User) -> dict[str, Any]:
    settings = get_settings()
    return {
        "document_bytes": settings.max_upload_bytes,
        "text_bytes": settings.max_text_upload_bytes,
        "image_bytes": settings.max_image_upload_bytes,
        "library_bytes": settings.max_library_bytes,
        "library_used_bytes": _library_bytes(db, user.id),
        "page_renderer_available": renderer.available(),
        "extensions": {
            group: sorted(ext for ext, (kind, _) in ALLOWED_EXTENSIONS.items() if _group(kind) == group)
            for group in ("document", "text", "image")
        },
    }


def _group(kind: str) -> str:
    return "text" if kind in TEXT_KINDS else "image" if kind == "image" else "document"


def _check_space(db: Session, user: User, size: int) -> None:
    settings = get_settings()
    if _library_bytes(db, user.id) + size > settings.max_library_bytes:
        raise ApiError(
            413,
            "library_full",
            f"Your library has reached its storage limit ({megabytes(settings.max_library_bytes)}). Delete files "
            "you no longer need, or raise the limit (RS_MAX_LIBRARY_BYTES).",
        )
    try:
        free = shutil.disk_usage(settings.storage_dir).free
    except OSError:  # pragma: no cover - storage_dir is created at start-up
        return
    if free - size < settings.min_free_disk_bytes:
        raise ApiError(
            507,
            "storage_low",
            "The disk RecallSpring stores files on is almost full, so uploads are paused to protect the server. "
            "Free some space, then upload again.",
        )


def parse_message(source: Source) -> str | None:
    if source.kind == "image":
        return None
    if source.parse_state == "failed":
        code = source.parse_error or ""
        return KIND_PARSE_MESSAGES.get((code, source.kind)) or PARSE_MESSAGES.get(code, "Text couldn't be extracted.")
    if source.parse_state == "needs_attention":
        notes = {n.split(":", 1)[0]: n.split(":", 1)[1] if ":" in n else "" for n in source.parse_notes}
        messages = []
        if "pages_without_text" in notes:
            pages = notes["pages_without_text"].replace(",", ", ")
            messages.append(
                f"Some pages have no extractable text (possibly scanned): {pages}. "
                "Claude can look at these pages on request."
            )
        if "slides_without_text" in notes:
            slides = notes["slides_without_text"].replace(",", ", ")
            messages.append(
                f"Many slides have little or no text: {slides}. Claude can look at the pictures on them on request."
            )
        if "pictures_only" in notes:
            messages.append("This document has only pictures. Claude can look at them on request.")
        if "truncated" in notes:
            messages.append("The file is very large, so only its beginning was extracted. Split it to get the rest.")
        return " ".join(messages) or None
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
    if existing is None:
        try:
            _check_space(db, user, size)
        except ApiError:
            tmp.unlink(missing_ok=True)
            raise
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
