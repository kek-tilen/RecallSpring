"""``recallspring shadow-report`` (ADR-014 §5): what FSRS-6 in shadow would have done, for the owner's checkpoint.

Local only and deterministic: it reads ``review_shadow``, review states, targets and availability, never calls a
model and never changes anything. Sections:

1. **Prediction:** log loss of FSRS's R before each review against a constant baseline, the learner's running pass
   rate before that day (both from earlier reviews only), per variant, with a bootstrap 90 % interval of the gain.
   A pass is any rating but Again under that variant's mapping.
2. **Workload:** reviews and minutes per day under the ladder and under FSRS with its cap, on the shadow days and in
   the next 14 days, against the learner's available minutes.
3. **Exam morning:** per exam, how many concepts in its scope FSRS estimated below T on the exam morning given the
   reviews that happened, and how many reviews FSRS with its cap asked for before the exam that did not happen.
4. **The Partial question:** how the next review went after a Fragile, a Partial and a Solid answer.
5. **Graders:** the graders and confidences behind the reviews, and the evidence the shadow leaves out.

R is FSRS's estimate fitted on other people's flashcards with default parameters: never a chance of remembering,
never a measure of mastery (ADR-014 §7).
"""

from __future__ import annotations

import math
import random
import statistics
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..learning import fsrs_shadow
from ..learning.scheduler import exam_target
from ..models import (
    Assessment,
    Attempt,
    Concept,
    Course,
    QuestionConcept,
    Quiz,
    ReviewShadow,
    ReviewState,
    StudyTarget,
    User,
)
from . import pace
from .reviews import effective_assessment

BOOTSTRAP = 2000
MIN_FOR_INTERVAL = 10
SWITCH_MIN_REVIEWS = 100
AHEAD_DAYS = 14
EPS = 1e-6


def _log_loss(y: int, p: float) -> float:
    p = min(1 - EPS, max(EPS, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def prediction(rows: list[ReviewShadow]) -> dict[str, Any]:
    """FSRS against the running pass rate; reviews of a concept after its first one, at least a day apart."""
    evaluable = sorted(
        (r for r in rows if r.seq > 1 and r.r_before is not None and r.source == "answer"),
        key=lambda r: (r.local_date, str(r.concept_id)),
    )
    passes = seen = 0
    pending: list[int] = []
    day: date | None = None
    model: list[float] = []
    base: list[float] = []
    for r in evaluable:
        if r.local_date != day:  # the baseline uses earlier days only
            passes += sum(pending)
            seen += len(pending)
            pending, day = [], r.local_date
        y = 1 if r.rating > 1 else 0
        model.append(_log_loss(y, float(r.r_before or 0)))
        base.append(_log_loss(y, (passes + 1) / (seen + 2)))
        pending.append(y)
    n = len(evaluable)
    out: dict[str, Any] = {"reviews": n, "pass_rate": None, "fsrs": None, "baseline": None, "gain": None}
    out["interval90"] = None
    out["beats_baseline"] = False
    if not n:
        return out
    gains = [b - m for b, m in zip(base, model, strict=True)]
    out |= {
        "pass_rate": sum(1 for r in evaluable if r.rating > 1) / n,
        "fsrs": statistics.fmean(model),
        "baseline": statistics.fmean(base),
        "gain": statistics.fmean(gains),
    }
    if n >= MIN_FOR_INTERVAL:
        rng = random.Random(14)  # fixed: the same data always give the same interval
        means = sorted(statistics.fmean(rng.choices(gains, k=n)) for _ in range(BOOTSTRAP))
        low, high = means[int(0.05 * BOOTSTRAP)], means[int(0.95 * BOOTSTRAP) - 1]
        out["interval90"] = [low, high]
        out["beats_baseline"] = low > 0
    return out


def _latest(rows: list[ReviewShadow]) -> dict[uuid.UUID, ReviewShadow]:
    out: dict[uuid.UUID, ReviewShadow] = {}
    for r in rows:
        if r.concept_id not in out or r.seq > out[r.concept_id].seq:
            out[r.concept_id] = r
    return out


def workload(
    db: Session, user: User, rows_by_variant: dict[str, list[ReviewShadow]], live: set[uuid.UUID], today: date
) -> dict[str, Any]:
    from .planner import minutes_available  # the planner imports the review service

    tz = ZoneInfo(user.timezone)
    minutes = pace.estimates(db, user)["standard"]["minutes"]
    variants = list(rows_by_variant)
    first = rows_by_variant[variants[0]]
    happened = Counter(r.local_date for r in first if r.concept_id in live)
    wanted = {v: Counter(r.capped_due for r in rows if r.concept_id in live) for v, rows in rows_by_variant.items()}

    def summary(days: list[date], counts: dict[str, Counter[date]]) -> dict[str, Any]:
        available = {d: minutes_available(db, user, d) for d in days}
        out: dict[str, Any] = {"days": len(days), "minutes_per_review": minutes}
        for name, counter in counts.items():
            per_day = [counter.get(d, 0) for d in days]
            out[name] = {
                "reviews": sum(per_day),
                "per_day": statistics.fmean(per_day) if per_day else 0.0,
                "max_day": max(per_day, default=0),
                "days_over_available": sum(1 for d, k in zip(days, per_day, strict=True) if k * minutes > available[d]),
            }
        return out

    start = min((r.local_date for r in first), default=today)
    past = [start + timedelta(days=i) for i in range((today - start).days)]
    ahead = [today + timedelta(days=i) for i in range(AHEAD_DAYS)]
    ladder_ahead: Counter[date] = Counter()
    for state in db.scalars(select(ReviewState).where(ReviewState.user_id == user.id)):
        if state.concept_id in live:
            ladder_ahead[max(today, state.due_at.astimezone(tz).date())] += 1
    fsrs_ahead = {
        v: Counter(max(today, r.capped_due) for cid, r in _latest(rows).items() if cid in live)
        for v, rows in rows_by_variant.items()
    }
    return {
        # On the shadow days the reviews that happened came from the ladder (with its exam layer) and the learner's
        # own practice; FSRS's line counts the dates it asked for.
        "shadow_days": summary(past, {"happened": happened, **wanted}),
        "next_days": summary(ahead, {"ladder": ladder_ahead, **fsrs_ahead}),
    }


def exam_mornings(
    db: Session, user: User, rows_by_variant: dict[str, list[ReviewShadow]], live: set[uuid.UUID], today: date
) -> list[dict[str, Any]]:
    from .targets import scope_concepts

    targets = db.scalars(
        select(StudyTarget)
        .join(Course, Course.id == StudyTarget.course_id)
        .where(
            Course.user_id == user.id,
            Course.deleted_at.is_(None),
            StudyTarget.deleted_at.is_(None),
            StudyTarget.status != "cancelled",
        )
        .order_by(StudyTarget.due_date, StudyTarget.created_at)
    ).all()
    out: list[dict[str, Any]] = []
    for target in targets:
        exam_day, t = target.due_date, exam_target(target.goal, target.exam_retention)
        scope = scope_concepts(db, target) & live
        entry: dict[str, Any] = {
            "name": target.name,
            "date": exam_day.isoformat(),
            "passed": exam_day < today,
            "target": t,
            "concepts": len(scope),
        }
        for variant, rows in rows_by_variant.items():
            before: dict[uuid.UUID, ReviewShadow] = {}
            for r in rows:
                if r.concept_id in scope and r.local_date < exam_day:
                    if r.concept_id not in before or r.seq > before[r.concept_id].seq:
                        before[r.concept_id] = r
            below = asked = 0
            for r in before.values():
                if fsrs_shadow.retrievability(r.s_after, r.d_after, r.local_date, exam_day) < t:
                    below += 1
                if r.capped_due < exam_day and r.capped_due < today:  # FSRS wanted a review before the exam
                    asked += 1
            entry[variant] = {"reviewed": len(before), "below_target": below, "review_asked_not_done": asked}
        out.append(entry)
    return out


def partial_question(rows: list[ReviewShadow]) -> dict[str, Any]:
    by_concept: dict[uuid.UUID, list[ReviewShadow]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: (str(r.concept_id), r.seq)):
        by_concept[r.concept_id].append(r)
    groups: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for reviews in by_concept.values():
        for a, b in zip(reviews, reviews[1:], strict=False):
            if a.source == "answer" and b.source == "answer" and a.grade is not None and b.grade is not None:
                groups[a.grade].append((b.grade, b.elapsed_days or 0))
    out: dict[str, Any] = {}
    for grade in range(5):
        nexts = groups.get(grade, [])
        out[str(grade)] = {
            "next_reviews": len(nexts),
            "next_solid_or_better": (sum(1 for g, _ in nexts if g >= 3) / len(nexts)) if nexts else None,
            "next_partial_or_better": (sum(1 for g, _ in nexts if g >= 2) / len(nexts)) if nexts else None,
            "median_days_between": statistics.median(d for _, d in nexts) if nexts else None,
        }
    return out


def graders(db: Session, user: User, rows: list[ReviewShadow], live: set[uuid.UUID]) -> dict[str, Any]:
    used = Counter(
        f"{r.evaluator_kind}/{r.confidence}" if r.source == "answer" else "check_first"
        for r in rows
        if r.concept_id in live
    )
    pairs = db.execute(
        select(Attempt, Assessment, QuestionConcept.concept_id, Quiz.mode)
        .join(Assessment, Assessment.attempt_id == Attempt.id)
        .join(QuestionConcept, QuestionConcept.question_id == Attempt.question_id)
        .outerjoin(Quiz, Quiz.id == Attempt.quiz_id)
        .where(Attempt.user_id == user.id)
    ).all()
    grouped: dict[tuple[uuid.UUID, uuid.UUID], list[Assessment]] = defaultdict(list)
    mode_of: dict[tuple[uuid.UUID, uuid.UUID], str | None] = {}
    for attempt, assessment, concept_id, mode in pairs:
        if concept_id in live:
            grouped[(attempt.id, concept_id)].append(assessment)
            mode_of[(attempt.id, concept_id)] = mode
    left_out: Counter[str] = Counter()
    certain = 0
    for key, assessments in grouped.items():
        eff = effective_assessment(assessments)
        if eff is None:
            continue
        if mode_of[key] == "diagnostic":
            left_out["check_first_answer"] += 1
        elif eff.evaluator_kind == "self":
            left_out["self_assessed"] += 1
        elif eff.status != "final" or eff.grade is None:
            left_out[eff.status] += 1
        elif eff.confidence == "low":
            left_out["low_confidence"] += 1
        else:
            certain += 1
    answers_used = sum(k for name, k in used.items() if name != "check_first")
    left_out["later_the_same_day"] = max(0, certain - answers_used)
    return {"reviews": dict(sorted(used.items())), "left_out": dict(sorted(left_out.items()))}


def build(db: Session, user: User, now: datetime) -> dict[str, Any]:
    today = now.astimezone(ZoneInfo(user.timezone)).date()
    rows = list(
        db.scalars(
            select(ReviewShadow)
            .where(ReviewShadow.user_id == user.id)
            .order_by(ReviewShadow.variant, ReviewShadow.concept_id, ReviewShadow.seq)
        )
    )
    live = set(
        db.scalars(
            select(Concept.id)
            .join(Course, Course.id == Concept.course_id)
            .where(Course.user_id == user.id, Concept.deleted_at.is_(None), Course.deleted_at.is_(None))
        )
    )
    rows = [r for r in rows if r.concept_id in live]
    by_variant = {v: [r for r in rows if r.variant == v] for v in fsrs_shadow.VARIANTS}
    first = by_variant[fsrs_shadow.VARIANTS[0]]
    exams = exam_mornings(db, user, by_variant, live, today)
    predictions = {v: prediction(r) for v, r in by_variant.items()}
    evaluable = predictions[fsrs_shadow.VARIANTS[0]]["reviews"]
    work = workload(db, user, by_variant, live, today)
    passed_with_data = [e for e in exams if e["passed"] and e[fsrs_shadow.VARIANTS[0]]["reviewed"] > 0]
    return {
        "user": user.username,
        "generated_on": today.isoformat(),
        "engine": {
            "library": "py-fsrs",
            "library_version": fsrs_shadow.LIBRARY_VERSION,
            "params_hash": fsrs_shadow.PARAMS_HASH,
            "parameters": "default",
            "desired_retention": fsrs_shadow.DESIRED_RETENTION,
            "maximum_interval": fsrs_shadow.MAXIMUM_INTERVAL,
            "variants": {"rs-fsrs6-v1": "Partial as Hard", "rs-fsrs6-v1a": "Partial as Again"},
        },
        "data": {
            "concepts": len({r.concept_id for r in first}),
            "reviews": len(first),
            "first_day": min((r.local_date.isoformat() for r in first), default=None),
            "last_day": max((r.local_date.isoformat() for r in first), default=None),
            "evaluable_reviews": evaluable,
        },
        "prediction": predictions,
        "workload": work,
        "exam_mornings": exams,
        "partial_question": partial_question(first),
        "graders": graders(db, user, first, live),
        "switch_criteria": {
            "exam_cycle": bool(passed_with_data),
            "reviews_100": evaluable >= SWITCH_MIN_REVIEWS,
            "beats_baseline": [v for v, p in predictions.items() if p["beats_baseline"]],
            "fits_availability": [v for v in fsrs_shadow.VARIANTS if work["shadow_days"][v]["days_over_available"] == 0]
            if work["shadow_days"]["days"]
            else [],
        },
    }


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{100 * x:.0f} %"


def _days(x: float | None) -> str:
    return "-" if x is None else f"{x:g}"


def _num(x: float | None, digits: int = 3) -> str:
    return "-" if x is None else f"{x:.{digits}f}"


def render(report: dict[str, Any]) -> str:
    e, d = report["engine"], report["data"]
    lines = [
        f"# FSRS-6 shadow report: {report['user']} ({report['generated_on']})",
        "",
        f"Engine: {e['library']} {e['library_version']}, {e['parameters']} parameters (hash {e['params_hash']}), "
        f"desired retention {e['desired_retention']}, maximum interval {e['maximum_interval']} days. "
        "Variants: rs-fsrs6-v1 (Partial as Hard), rs-fsrs6-v1a (Partial as Again).",
        f"Data: {d['reviews']} review(s) of {d['concepts']} concept(s), {d['first_day'] or '-'} to "
        f"{d['last_day'] or '-'}; {d['evaluable_reviews']} evaluable (a concept's later reviews).",
        "R is FSRS's estimate with default parameters fitted on other people's flashcards: not a chance of "
        "remembering and not a measure of mastery. Nothing here is shown in the app or used for dates.",
        "",
        "## 1. Prediction (log loss, lower is better; baseline: your running pass rate)",
        "",
    ]
    for variant, p in report["prediction"].items():
        interval = p["interval90"]
        span = f"[{_num(interval[0])}, {_num(interval[1])}]" if interval else "not enough reviews"
        lines.append(
            f"- {variant}: {p['reviews']} review(s), pass rate {_pct(p['pass_rate'])}; FSRS {_num(p['fsrs'])}, "
            f"baseline {_num(p['baseline'])}, gain {_num(p['gain'])} (90 % interval {span})"
        )
    lines += ["", "## 2. Workload (reviews per day; minutes use your standard review estimate)", ""]
    for label, key in (("On the shadow days", "shadow_days"), (f"Next {AHEAD_DAYS} days", "next_days")):
        w = report["workload"][key]
        lines.append(f"{label} ({w['days']} day(s), {w['minutes_per_review']} min per review):")
        for name, v in w.items():
            if isinstance(v, dict):
                lines.append(
                    f"- {name}: {v['reviews']} review(s), {_num(v['per_day'], 1)} a day, at most {v['max_day']}, "
                    f"{v['days_over_available']} day(s) over your available minutes"
                )
    lines += ["", "## 3. Exam mornings (concepts below T by FSRS's estimate, given the reviews that happened)", ""]
    for x in report["exam_mornings"]:
        when = "passed" if x["passed"] else "upcoming, so far"
        parts = [
            f"{v}: {x[v]['below_target']} of {x[v]['reviewed']} reviewed below T; FSRS asked for "
            f"{x[v]['review_asked_not_done']} review(s) before the exam that did not happen"
            for v in fsrs_shadow.VARIANTS
        ]
        head = f"- {x['name']} ({x['date']}, {when}, T {x['target']}, {x['concepts']} concept(s)): "
        lines.append(head + "; ".join(parts))
    if not report["exam_mornings"]:
        lines.append("- No exams yet.")
    lines += ["", "## 4. The Partial question (the next review after each grade)", ""]
    names = {0: "No evidence", 1: "Fragile", 2: "Partial", 3: "Solid", 4: "Transfer"}
    for grade, q in report["partial_question"].items():
        lines.append(
            f"- After {names[int(grade)]}: {q['next_reviews']} next review(s), "
            f"Solid or better {_pct(q['next_solid_or_better'])}, Partial or better "
            f"{_pct(q['next_partial_or_better'])}, median {_days(q['median_days_between'])} day(s) later"
        )
    g = report["graders"]
    lines += ["", "## 5. Graders", ""]
    lines.append("- Behind the reviews: " + (", ".join(f"{k} {v}" for k, v in g["reviews"].items()) or "none"))
    lines.append("- Left out: " + (", ".join(f"{k} {v}" for k, v in g["left_out"].items() if v) or "nothing"))
    c = report["switch_criteria"]
    lines += [
        "",
        "## Phase B criteria (the owner decides; nothing switches by itself)",
        "",
        f"- One full exam cycle in shadow: {'yes' if c['exam_cycle'] else 'not yet'}",
        f"- At least {SWITCH_MIN_REVIEWS} evaluable reviews: {'yes' if c['reviews_100'] else 'not yet'} "
        f"({d['evaluable_reviews']})",
        f"- Beats the baseline with an interval above zero: {', '.join(c['beats_baseline']) or 'neither variant yet'}",
        f"- Fits your availability on the shadow days: {', '.join(c['fits_availability']) or 'neither variant yet'}",
        "",
    ]
    return "\n".join(lines)
