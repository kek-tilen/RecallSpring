"""iCalendar (RFC 5545) export of exams and kolokviji. Plain text built here; no third-party library."""

from __future__ import annotations

import uuid
from datetime import UTC, date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..models import Course, CourseGroup, StudyTarget, User

KIND = {"kolokvij": "Kolokvij", "izpit": "Exam", "other": "Exam"}


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Lines longer than 75 octets are folded with CRLF + space (RFC 5545 3.1), never inside a UTF-8 character."""
    out, current = [], b""
    for ch in line:
        encoded = ch.encode("utf-8")
        if len(current) + len(encoded) > (75 if not out else 74):
            out.append(current.decode("utf-8"))
            current = b""
        current += encoded
    out.append(current.decode("utf-8"))
    return "\r\n ".join(out)


def _ymd(day: date) -> str:
    return day.strftime("%Y%m%d")


def _group_ids(db: Session, user_id: uuid.UUID, root: uuid.UUID) -> list[uuid.UUID]:
    ids, frontier = [root], [root]
    while frontier:
        frontier = list(
            db.scalars(
                select(CourseGroup.id).where(CourseGroup.user_id == user_id, CourseGroup.parent_id.in_(frontier))
            )
        )
        ids += frontier
    return ids


def exams_ics(db: Session, user: User, group_id: uuid.UUID | None = None) -> str:
    stmt = (
        select(StudyTarget, Course)
        .join(Course, Course.id == StudyTarget.course_id)
        .where(
            StudyTarget.user_id == user.id,
            StudyTarget.deleted_at.is_(None),
            StudyTarget.status.in_(("upcoming", "failed")),
            Course.deleted_at.is_(None),
        )
        .order_by(StudyTarget.due_date)
    )
    if group_id is not None:
        stmt = stmt.where(Course.group_id.in_(_group_ids(db, user.id, group_id)))
    stamp = clock.now().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//RecallSpring//Exams//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:RecallSpring exams",
    ]
    for target, course in db.execute(stmt).all():
        summary = f"{course.title}: {target.name}"
        description = f"{KIND.get(target.kind, 'Exam')}. Scope: {target.scope_description}"
        if target.notes:
            description += f"\nNotes: {target.notes}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{target.id}@recallspring",
            f"DTSTAMP:{stamp}",
            f"SEQUENCE:{target.revision}",
            f"DTSTART;VALUE=DATE:{_ymd(target.due_date)}",
            f"DTEND;VALUE=DATE:{_ymd(target.due_date + timedelta(days=1))}",
            f"SUMMARY:{_escape(summary)}",
            f"DESCRIPTION:{_escape(description)}",
            "TRANSP:TRANSPARENT",
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_escape(summary)}",
            "TRIGGER:-P1D",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
