"""Weekly review (``week-v1``, docs/05 -> Weekly review): what happened in one week and what comes next.

Deterministic, no model calls; counts only what RecallSpring recorded. Weeks run Monday to Sunday in the learner's
timezone. Study time is counted only for study sessions that were closed with a summary (capped at four hours each),
so it is a lower bound, and the review says so.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import (
    Assessment,
    Attempt,
    Concept,
    Course,
    LearningEvent,
    Question,
    ReviewState,
    StudySession,
    StudyTarget,
    User,
)
from .planner import minutes_available
from .readiness import state_counts
from .reviews import effective_assessment

POLICY = "week-v1"
SESSION_CAP_MINUTES = 240
UPCOMING_DAYS = 21
MAX_WEEKS_BACK = 52
ACTIVE_EVENTS = {
    "attempt.submitted",
    "concept.studied",
    "concept.known",
    "quiz.submitted",
    "note.created",
    "note.saved",
    "study_session.summarised",
    "source.added",
    "assessment.corrected",
    "assessment.challenged",
}
NOTE = (
    "Counts what RecallSpring recorded. Study time includes only study sessions closed with a summary, so it can be "
    "less than the time you really studied."
)


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _grades(db: Session, user_id: uuid.UUID, start: datetime, end: datetime) -> list[tuple[Attempt, int]]:
    """Effective grades of the answers given between start and end (graded at any time)."""
    rows = db.execute(
        select(Attempt, Assessment)
        .join(Assessment, Assessment.attempt_id == Attempt.id)
        .where(Attempt.user_id == user_id, Attempt.submitted_at >= start, Attempt.submitted_at < end)
    ).all()
    per_attempt: dict[uuid.UUID, tuple[Attempt, list[Assessment]]] = {}
    for attempt, assessment in rows:
        per_attempt.setdefault(attempt.id, (attempt, []))[1].append(assessment)
    out = []
    for attempt, assessments in per_attempt.values():
        eff = effective_assessment(assessments)
        if eff is not None and eff.grade is not None:
            out.append((attempt, eff.grade))
    return out


def _average(grades: list[int]) -> float | None:
    return round(sum(grades) / len(grades), 1) if grades else None


def week_review(db: Session, user: User, now: datetime, weeks_ago: int = 0) -> dict[str, Any]:
    weeks_ago = max(0, min(MAX_WEEKS_BACK, weeks_ago))
    tz = ZoneInfo(user.timezone)
    today = now.astimezone(tz).date()
    monday = today - timedelta(days=today.weekday()) - timedelta(weeks=weeks_ago)
    sunday = monday + timedelta(days=6)
    start = datetime.combine(monday, time.min, tz)
    end = datetime.combine(sunday + timedelta(days=1), time.min, tz)
    days: list[date] = [monday + timedelta(days=d) for d in range(7) if monday + timedelta(days=d) <= today]
    planned = sum(minutes_available(db, user, d) for d in days)

    events = list(
        db.scalars(
            select(LearningEvent).where(
                LearningEvent.user_id == user.id, LearningEvent.occurred_at >= start, LearningEvent.occurred_at < end
            )
        )
    )
    by_type = Counter(e.event_type for e in events)
    active_days = sorted({e.occurred_at.astimezone(tz).date() for e in events if e.event_type in ACTIVE_EVENTS})

    sessions = list(
        db.scalars(
            select(StudySession).where(
                StudySession.user_id == user.id, StudySession.started_at >= start, StudySession.started_at < end
            )
        )
    )
    timed = [s for s in sessions if s.ended_at is not None and s.ended_at >= s.started_at]
    session_minutes = round(
        sum(min(SESSION_CAP_MINUTES, (s.ended_at - s.started_at).total_seconds() / 60) for s in timed)  # type: ignore[operator]
    )

    graded = _grades(db, user.id, start, end)
    previous = _grades(db, user.id, start - timedelta(days=7), start)
    grades = [g for _, g in graded]
    distribution = [grades.count(g) for g in range(5)]

    courses = {
        c.id: c for c in db.scalars(select(Course).where(Course.user_id == user.id, Course.deleted_at.is_(None)))
    }
    per_course: dict[uuid.UUID, dict[str, Any]] = defaultdict(lambda: {"answers": 0, "grades": [], "studied": 0})
    answered = list(
        db.execute(
            select(Attempt.id, Question.course_id)
            .join(Question, Question.id == Attempt.question_id)
            .where(Attempt.user_id == user.id, Attempt.submitted_at >= start, Attempt.submitted_at < end)
        )
    )
    course_of_attempt = dict(answered)
    for _, course_id in answered:
        per_course[course_id]["answers"] += 1
    for attempt, grade in graded:
        if attempt.id in course_of_attempt:
            per_course[course_of_attempt[attempt.id]]["grades"].append(grade)
    studied_ids = [e.entity_id for e in events if e.event_type in ("concept.studied", "concept.known")]
    if studied_ids:
        for course_id, n in db.execute(
            select(Concept.course_id, func.count()).where(Concept.id.in_(studied_ids)).group_by(Concept.course_id)
        ):
            per_course[course_id]["studied"] += n
    course_rows = sorted(
        (
            {
                "id": str(cid),
                "title": courses[cid].title,
                "color": courses[cid].color,
                "kind": courses[cid].kind,
                "answers": v["answers"],
                "graded": len(v["grades"]),
                "average_grade": _average(v["grades"]),
                "concepts_studied": v["studied"],
            }
            for cid, v in per_course.items()
            if cid in courses
        ),
        key=lambda r: (-(r["answers"] + r["concepts_studied"]), r["title"]),
    )

    reviews = None
    if weeks_ago == 0:
        due = select(func.count()).select_from(ReviewState).where(ReviewState.user_id == user.id)
        reviews = {
            "overdue": db.scalar(due.where(ReviewState.due_at <= now)) or 0,
            "due_next_7_days": db.scalar(
                due.where(ReviewState.due_at > now, ReviewState.due_at <= now + timedelta(days=7))
            )
            or 0,
        }

    exams = []
    if weeks_ago == 0:
        upcoming = db.execute(
            select(StudyTarget, Course)
            .join(Course, Course.id == StudyTarget.course_id)
            .where(
                StudyTarget.user_id == user.id,
                StudyTarget.deleted_at.is_(None),
                StudyTarget.status == "upcoming",
                StudyTarget.due_date >= today,
                StudyTarget.due_date <= today + timedelta(days=UPCOMING_DAYS),
                Course.deleted_at.is_(None),
                Course.status == "active",
            )
            .order_by(StudyTarget.due_date, StudyTarget.created_at)
        ).all()
        for target, course in upcoming:
            counts = state_counts(db, user, target, now)
            exams.append(
                {
                    "id": str(target.id),
                    "name": target.name,
                    "course_id": str(course.id),
                    "course_title": course.title,
                    "course_color": course.color,
                    "due_date": target.due_date.isoformat(),
                    "days_left": (target.due_date - today).days,
                    **counts,
                }
            )

    activity = {
        "answers": by_type["attempt.submitted"],
        "graded": len(grades),
        "concepts_studied": by_type["concept.studied"],
        "concepts_known": by_type["concept.known"],
        "simulations": by_type["quiz.submitted"],
        "notes": by_type["note.created"] + by_type["note.saved"],
        "materials": by_type["source.added"],
        "active_days": [d.isoformat() for d in active_days],
    }
    return {
        "policy_version": POLICY,
        "generated_at": now.isoformat(),
        "week": {
            "start": monday.isoformat(),
            "end": sunday.isoformat(),
            "weeks_ago": weeks_ago,
            "is_current": weeks_ago == 0,
            "days_counted": len(days),
        },
        "planned_minutes": planned,
        "session_minutes": session_minutes,
        "sessions": {"timed": len(timed), "untimed": len(sessions) - len(timed)},
        "activity": activity,
        "grades": {
            "count": len(grades),
            "average": _average(grades),
            "previous_average": _average([g for _, g in previous]),
            "distribution": distribution,
        },
        "courses": course_rows,
        "reviews": reviews,
        "exams": exams,
        "summary": _summary(
            weeks_ago, len(days), activity, grades, previous, planned, session_minutes, timed, reviews, exams
        ),
        "note": NOTE,
    }


def _summary(
    weeks_ago: int,
    days: int,
    activity: dict[str, Any],
    grades: list[int],
    previous: list[tuple[Attempt, int]],
    planned: int,
    minutes: int,
    timed: list[StudySession],
    reviews: dict[str, int] | None,
    exams: list[dict[str, Any]],
) -> list[str]:
    lines = []
    active = len(activity["active_days"])
    if not active:
        lines.append("No study recorded this week yet." if weeks_ago == 0 else "No study was recorded that week.")
    else:
        parts = [_plural(activity["answers"], "answer")]
        studied = activity["concepts_studied"] + activity["concepts_known"]
        parts.append(f"{_plural(studied, 'concept')} studied")
        if activity["simulations"]:
            parts.append(_plural(activity["simulations"], "simulation"))
        lines.append(f"Active on {active} of {_plural(days, 'day')}: {', '.join(parts)}.")
    if grades:
        avg = _average(grades)
        prev = _average([g for _, g in previous])
        trend = ""
        if prev is not None and avg is not None:
            trend = (
                f", up from {prev}" if avg > prev else f", down from {prev}" if avg < prev else ", the same as before"
            )
        lines.append(f"Average grade {avg}/4 over {_plural(len(grades), 'graded answer')}{trend}.")
    if timed:
        lines.append(
            f"About {minutes} min in {_plural(len(timed), 'study session')} closed with a summary; "
            f"{planned} min planned."
        )
    else:
        lines.append(f"{planned} min planned. No study session was closed with a summary, so no study time is counted.")
    if reviews and reviews["overdue"]:
        lines.append(f"{_plural(reviews['overdue'], 'review is', 'reviews are')} overdue.")
    for exam in exams[:3]:
        if exam["days_left"] > 14:
            continue
        open_work = []
        if exam["not_studied"]:
            open_work.append(f"{exam['not_studied']} not studied")
        if exam["weak"]:
            open_work.append(f"{exam['weak']} weak")
        if exam["not_practised"]:
            open_work.append(f"{exam['not_practised']} not practised")
        state = ", ".join(open_work) if open_work else "nothing open"
        when = "today" if exam["days_left"] == 0 else f"in {_plural(exam['days_left'], 'day')}"
        lines.append(
            f"{exam['name']} ({exam['course_title']}) {when}: {state} of {_plural(exam['concepts'], 'concept')}."
        )
    return lines
