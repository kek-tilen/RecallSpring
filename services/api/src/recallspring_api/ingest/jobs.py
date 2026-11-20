"""PostgreSQL job queue and worker for deterministic background work (never model calls).

Jobs are claimed with ``FOR UPDATE SKIP LOCKED`` and a lease, processed outside any transaction, then
finalized in a new transaction. Unexpected failures retry with backoff up to ``job_max_attempts``.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import clock
from ..config import get_settings
from ..db import new_session
from ..models import Job, Source, SourceSection
from ..services.events import learning_event
from . import extract as extractor
from .storage import blob_path

log = logging.getLogger("recallspring.worker")

EXTRACT_SOURCE = "extract_source"


class JobFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def enqueue(db: Session, *, user_id: uuid.UUID, type: str, payload: dict[str, Any]) -> Job:
    job = Job(user_id=user_id, type=type, payload=payload, state="queued", run_after=clock.now())
    db.add(job)
    return job


def _claim(db: Session) -> Job | None:
    now = clock.now()
    settings = get_settings()
    job = db.scalar(
        select(Job)
        .where(
            or_(
                (Job.state == "queued") & (Job.run_after <= now),
                (Job.state == "running") & (Job.locked_until < now),  # lease expired: worker died
            )
        )
        .order_by(Job.run_after, Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.state = "running"
    job.attempts += 1
    job.locked_until = now + timedelta(seconds=settings.job_lease_seconds)
    return job


# ---------------------------------------------------------------- extract_source


def run_extraction(kind: str, path: str, max_pages: int, suffix: str = "") -> extractor.Result:
    """Run the extractor in a separate Python process with a wall-clock timeout."""
    settings = get_settings()
    if settings.extraction_isolation == "inprocess":
        return extractor.extract(Path(path), kind, max_pages, suffix)
    cmd = [sys.executable, "-I", "-m", "recallspring_api.ingest.extract", kind, path, str(max_pages), suffix]
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            cmd, capture_output=True, timeout=settings.extraction_timeout_seconds, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise JobFailure("extraction_timeout") from exc
    if proc.returncode != 0:
        raise JobFailure("extraction_crashed")
    try:
        data = json.loads(proc.stdout.decode("utf-8"))
        sections = [extractor.Section(**s) for s in data.pop("sections")]
        return extractor.Result(sections=sections, **data)
    except (ValueError, TypeError, KeyError) as exc:
        raise JobFailure("extraction_crashed") from exc


def _start_extract(db: Session, job: Job) -> tuple[str, str, int, str] | None:
    source = db.get(Source, uuid.UUID(job.payload["source_id"]))
    if source is None or source.deleted_at is not None or source.version != job.payload["version"]:
        return None  # superseded or removed: nothing to do
    source.parse_state = "processing"
    suffix = Path(source.filename).suffix.lower()[:20]
    return source.kind, str(blob_path(source.storage_key)), get_settings().max_pdf_pages, suffix


def _finish_extract(db: Session, job: Job, result: extractor.Result) -> None:
    source = db.get(Source, uuid.UUID(job.payload["source_id"]))
    if source is None or source.version != job.payload["version"]:
        return
    now = clock.now()
    source.parse_state = result.status
    source.parse_error = result.error_code
    source.parse_notes = result.notes
    source.parser_version = result.parser_version
    source.page_count = result.page_count
    source.parsed_at = now
    for s in result.sections:
        db.add(
            SourceSection(
                user_id=source.user_id,
                source_id=source.id,
                source_version=source.version,
                position=s.position,
                page=s.page,
                heading=s.heading,
                citation_label=s.citation_label[:160],
                text=s.text,
                char_start=s.char_start,
                char_end=s.char_end,
                parser_version=result.parser_version,
            )
        )
    learning_event(
        db,
        user_id=source.user_id,
        entity_type="source",
        entity_id=source.id,
        event_type="source.parsed",
        payload={
            "state": result.status,
            "error": result.error_code,
            "sections": len(result.sections),
            "version": source.version,
        },
        request_id=None,
    )


def _fail_extract(db: Session, job: Job, code: str) -> None:
    source = db.get(Source, uuid.UUID(job.payload["source_id"]))
    if source is not None and source.version == job.payload["version"]:
        source.parse_state = "failed"
        source.parse_error = code
        source.parsed_at = clock.now()


# ---------------------------------------------------------------- worker loop


def run_once() -> bool:
    """Claim and process one job. Returns False when no job was available."""
    settings = get_settings()
    with new_session() as db:
        job = _claim(db)
        if job is None:
            return False
        job_id = job.id
        work = _start_extract(db, job) if job.type == EXTRACT_SOURCE else None
        db.commit()

    error: str | None = None
    result: extractor.Result | None = None
    if work is not None:
        try:
            result = run_extraction(*work)
        except JobFailure as exc:
            error = exc.code

    with new_session() as db:
        job = db.get(Job, job_id, with_for_update=True)
        assert job is not None
        if error is None:
            if result is not None:
                _finish_extract(db, job, result)
            job.state, job.locked_until, job.last_error = "succeeded", None, None
        elif job.attempts >= settings.job_max_attempts:
            _fail_extract(db, job, error)
            job.state, job.locked_until, job.last_error = "failed", None, error
        else:
            job.state, job.locked_until, job.last_error = "queued", None, error
            job.run_after = clock.now() + timedelta(seconds=30 * 2 ** (job.attempts - 1))
        db.commit()
    log.info("job %s finished state=%s error=%s", job_id, job.state, error)
    return True


def run_pending(limit: int = 100) -> int:
    processed = 0
    while processed < limit and run_once():
        processed += 1
    return processed


def run_worker(poll_seconds: float = 2.0, should_stop: Callable[[], bool] = lambda: False) -> None:
    log.info("worker started")
    while not should_stop():
        if not run_once():
            time.sleep(poll_seconds)
