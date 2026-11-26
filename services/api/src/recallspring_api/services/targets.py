"""Study targets (kolokvij / izpit): scope resolution, active target and the study context Claude starts from."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import clock
from ..errors import ApiError
from ..learning.scheduler import BEFORE_EXAM, before_exam_choice, exam_target
from ..models import (
    Concept,
    ConceptSource,
    Course,
    Quiz,
    ReviewState,
    Source,
    SourceSection,
    StudySession,
    StudyTarget,
    StudyTargetScope,
    SyllabusItem,
    TargetProfile,
    User,
)
from ..schemas import ProfilePaperIn, ProfileTopicIn, TargetIn, TargetScopeItem, TargetUpdateIn
from .events import audit, learning_event
from .ownership import owned

SETUP_QUESTIONS = [
    "What are you preparing for: the 1st kolokvij, the 2nd kolokvij, or the exam (whole course or only a part, "
    "because you already passed something)?",
    "When is it (date)?",
    "From which material to which material (e.g. lectures 1-6, or pages 1-80 of the script)?",
    "Do you have an old kolokvij or exam paper I can use to match the question style?",
    "Anything special to know (allowed aids, only calculations, topics the lecturer emphasises, ...)?",
]


def live_targets(db: Session, course_id: uuid.UUID) -> list[StudyTarget]:
    return list(
        db.scalars(
            select(StudyTarget)
            .where(StudyTarget.course_id == course_id, StudyTarget.deleted_at.is_(None))
            .order_by(StudyTarget.due_date, StudyTarget.created_at)
        )
    )


def active_target(targets: list[StudyTarget], today: date) -> StudyTarget | None:
    """The nearest upcoming target that is today or later; a failed target stays relevant for the retake."""
    upcoming = [t for t in targets if t.status == "upcoming" and t.due_date >= today]
    return upcoming[0] if upcoming else None


def scope_concepts(db: Session, target: StudyTarget) -> set[uuid.UUID]:
    """Concepts covered by a target. No scope rows means the whole course."""
    rows = list(db.scalars(select(StudyTargetScope).where(StudyTargetScope.target_id == target.id)))
    course_concepts = select(Concept.id).where(Concept.course_id == target.course_id, Concept.deleted_at.is_(None))
    if not rows:
        return set(db.scalars(course_concepts))
    concepts: set[uuid.UUID] = set()
    for row in rows:
        if row.kind == "concept" and row.concept_id:
            concepts.add(row.concept_id)
        elif row.kind == "topic" and row.syllabus_item_id:
            concepts |= set(db.scalars(course_concepts.where(Concept.syllabus_item_id == row.syllabus_item_id)))
        elif row.kind in ("source", "pages") and row.source_id:
            section_filter = [SourceSection.source_id == row.source_id]
            if row.kind == "pages":
                section_filter += [
                    SourceSection.page >= (row.page_from or 1),
                    SourceSection.page <= (row.page_to or 100_000),
                ]
            concepts |= set(
                db.scalars(
                    select(ConceptSource.concept_id)
                    .join(SourceSection, SourceSection.id == ConceptSource.section_id)
                    .where(*section_filter)
                )
            )
    return concepts


def scope_view(db: Session, target: StudyTarget) -> list[dict[str, Any]]:
    out = []
    for row in db.scalars(select(StudyTargetScope).where(StudyTargetScope.target_id == target.id)):
        item: dict[str, Any] = {"kind": row.kind}
        if row.source_id:
            src = db.get(Source, row.source_id)
            item["source_id"] = str(row.source_id)
            item["filename"] = src.filename if src else None
        if row.kind == "pages":
            item["pages"] = [row.page_from, row.page_to]
        if row.syllabus_item_id:
            item["topic_id"] = str(row.syllabus_item_id)
        if row.concept_id:
            item["concept_id"] = str(row.concept_id)
        out.append(item)
    return out


def latest_profile(db: Session, target_id: uuid.UUID) -> TargetProfile | None:
    return db.scalar(
        select(TargetProfile)
        .where(TargetProfile.target_id == target_id)
        .order_by(TargetProfile.created_at.desc())
        .limit(1)
    )


# ---------------------------------------------------------------- exam profile v2 (ADR-013 §1)

RECURRENCE = {2: 1.25, 3: 1.5}  # a topic on 2 papers counts x1.25, on 3 or more x1.5


def topic_weight(share: float | None, topics: int, papers_seen: int) -> float:
    """A topic's weight for planning (0.5-2): its share of the points against an average topic's share, raised when
    it recurs on several papers. Without a share a topic counts as average (1.0)."""
    base = 1.0 if share is None or topics == 0 else share * topics
    factor = RECURRENCE[min(papers_seen, 3)] if papers_seen >= 2 else 1.0
    return round(min(2.0, max(0.5, base * factor)), 2)


def computed_topics(topics: list[ProfileTopicIn], papers: list[ProfilePaperIn]) -> list[dict[str, Any]]:
    """Each topic as stored: what the assistant read, plus the share of the points and the weight RecallSpring
    computes. Points count against the papers' total points (or the sum of the topics' points when a total is
    missing); a share is taken as given. A topic that appears only on papers used for their style (``use="style"``,
    e.g. a paper of another kolokvij) is kept as ``style_only`` with weight 1.0: it does not change the plan."""
    totals = [p.total_points for p in papers]
    total = sum(t for t in totals if t) if totals and all(totals) else sum(t.points or 0 for t in topics)
    out = []
    for t in topics:
        share = t.points / total if t.points is not None and total > 0 else t.share
        on = [p for p in papers if p.label in t.papers] if t.papers else papers
        counted = [p for p in on if p.use == "style_and_topics"]
        style_only = bool(on) and not counted
        seen = (len(counted) if t.papers else len(set(t.papers))) or 1
        out.append(
            {
                "label": t.label,
                "concept_ids": [str(c) for c in dict.fromkeys(t.concept_ids)],
                "not_in_material": t.not_in_material,
                "points": t.points,
                "share": round(share, 4) if share is not None else None,
                "where": t.where,
                "papers": list(dict.fromkeys(t.papers)),
                "style_only": style_only,
                "weight": 1.0 if style_only else topic_weight(share, len(topics), seen),
            }
        )
    return out


def check_profile_topics(
    db: Session, user: User, course_id: uuid.UUID, topics: list[ProfileTopicIn], papers: list[ProfilePaperIn]
) -> None:
    """Nothing in a profile is silently ignored: every topic names concepts of this course or says it is not in the
    material, and names only papers the profile lists."""
    labels = {p.label for p in papers if p.label}
    for index, t in enumerate(topics):
        if not t.concept_ids and not t.not_in_material:
            raise ApiError(
                422,
                "topic_not_mapped",
                f"Topic '{t.label}' names no concept. Link the course concepts that cover it (create them first if "
                "needed), or set not_in_material when the course material does not cover it.",
                {"index": index},
            )
        if t.concept_ids and t.not_in_material:
            raise ApiError(
                422,
                "topic_mapping_unclear",
                f"Topic '{t.label}' names concepts and says it is not in the material; choose one.",
                {"index": index},
            )
        for cid in t.concept_ids:
            concept = db.get(Concept, cid)
            if concept is None or concept.user_id != user.id or concept.course_id != course_id:
                raise ApiError(
                    422, "invalid_weight", "A topic refers to a concept outside this course.", {"index": index}
                )
        unknown = [p for p in t.papers if p not in labels]
        if unknown:
            raise ApiError(
                422,
                "unknown_paper",
                f"Topic '{t.label}' names a paper the profile does not list: {', '.join(unknown)}.",
                {"index": index},
            )


def concept_weights(profile: TargetProfile | None) -> dict[str, float]:
    """Planning weight per concept from the latest profile: v2 topics (the highest weight of the topics a concept
    covers) or v1 topic weights linked to a concept."""
    weights: dict[str, float] = {}
    if profile is None:
        return weights
    if profile.version >= 2:
        for t in profile.topics:
            if not isinstance(t, dict):
                continue
            for cid in t.get("concept_ids") or []:
                weights[str(cid)] = max(weights.get(str(cid), 0.0), float(t.get("weight", 1.0)))
        return weights
    for w in profile.topic_weights:
        if isinstance(w, dict) and w.get("concept_id"):
            try:
                weights[str(w["concept_id"])] = max(0.5, min(2.0, float(w.get("weight", 1.0))))
            except (TypeError, ValueError):
                continue
    return weights


def confirm_profile(
    db: Session,
    user: User,
    target_id: uuid.UUID,
    profile_id: uuid.UUID,
    via: str,
    now: datetime,
    request_id: str,
) -> StudyTarget:
    """The learner confirms that the latest analysis matches the paper (ADR-013 §1). Only the latest v2 analysis can
    be confirmed; confirming twice changes nothing. Audited."""
    target = owned(db, StudyTarget, target_id, user.id)
    if target.deleted_at is not None:
        raise ApiError(404, "not_found", "Study target not found.")
    profile = latest_profile(db, target.id)
    if profile is None:
        raise ApiError(404, "no_profile", "This exam has no analysis of an old paper yet.")
    if profile.id != profile_id:
        raise ApiError(
            409,
            "profile_changed",
            "A newer analysis of this exam exists. Show the learner the latest one before confirming.",
            {"latest_profile_id": str(profile.id)},
        )
    if profile.version < 2:
        raise ApiError(
            409,
            "analyse_again",
            "This analysis was made before analyses were confirmed and its topics may not be linked to the material. "
            "Analyse the paper again (record_exam_profile), then ask the learner to confirm.",
        )
    missing = papers_not_looked_at(db, profile) if via == "assistant" else []
    if missing:
        raise ApiError(
            409,
            "papers_not_looked_at",
            "The analysis has not looked at every past paper of this course: "
            + ", ".join(m["filename"] for m in missing)
            + ". Look at each one, ask the learner which exam it was for when that is unclear, and record the profile "
            "again with it in papers (further photos of the same paper in extra_source_ids) or in skipped_papers with "
            "the learner's reason.",
            {"not_looked_at": missing},
        )
    unproven = evidence_gaps(db, profile)["missing"] if via == "assistant" else []
    if unproven:
        raise ApiError(
            409,
            "evidence_missing",
            "Say for every file of a paper what shows that it belongs to it (papers[].evidence: why and strength): "
            + ", ".join(m["filename"] for m in unproven)
            + ". Record the profile again; ask the learner about every file whose evidence is weak.",
            {"evidence_missing": unproven},
        )
    if profile.confirmed_at is None:
        profile.confirmed_at = now
        profile.confirmed_via = via
        audit(
            db,
            actor_id=user.id,
            action="exam_profile.confirmed",
            target_type="target_profile",
            target_id=profile.id,
            details={"via": via},
            request_id=request_id,
        )
        learning_event(
            db,
            user_id=user.id,
            entity_type="study_target",
            entity_id=target.id,
            event_type="target.profile_confirmed",
            payload={"profile_id": str(profile.id), "via": via},
            request_id=request_id,
        )
        db.flush()
    return target


def _source_ref(db: Session, source_id: Any) -> dict[str, Any] | None:
    if not source_id:
        return None
    try:
        src = db.get(Source, uuid.UUID(str(source_id)))
    except ValueError:
        return None
    if src is None:
        return None
    return {"id": str(src.id), "filename": src.filename, "removed": src.deleted_at is not None}


def _covered(profile: TargetProfile) -> set[str]:
    """Sources the analysis read or left out on the learner's word."""
    ids = {str(profile.source_id)} if profile.source_id else set()
    for p in profile.papers or []:
        if isinstance(p, dict):
            ids.update(str(i) for i in [p.get("source_id"), *(p.get("extra_source_ids") or [])] if i)
    ids.update(str(s.get("source_id")) for s in profile.skipped_papers or [] if isinstance(s, dict))
    return ids


def _paper_files(db: Session, paper: dict[str, Any]) -> list[dict[str, Any]]:
    """Every file of a paper in RecallSpring, the first one first, with the stated reason it belongs to the paper."""
    given = {str(e.get("source_id")): e for e in paper.get("evidence") or [] if isinstance(e, dict)}
    out = []
    for source_id in [paper.get("source_id"), *(paper.get("extra_source_ids") or [])]:
        ref = _source_ref(db, source_id)
        if ref is not None:
            e = given.get(str(source_id)) or {}
            out.append({**ref, "why": e.get("why"), "strength": e.get("strength")})
    return out


def evidence_gaps(db: Session, profile: TargetProfile) -> dict[str, list[dict[str, Any]]]:
    """Files of the analysed papers without a stated reason why they belong to the paper (missing), and those whose
    reason is only inferred (weak), owner 2026-11-25."""
    missing: list[dict[str, Any]] = []
    weak: list[dict[str, Any]] = []
    for p in profile.papers or []:
        if not isinstance(p, dict):
            continue
        given = {str(e.get("source_id")): e for e in p.get("evidence") or [] if isinstance(e, dict)}
        for source_id in [p.get("source_id"), *(p.get("extra_source_ids") or [])]:
            ref = _source_ref(db, source_id)
            if ref is None:
                continue
            e = given.get(str(source_id))
            if e is None:
                missing.append(ref)
            elif e.get("strength") == "weak":
                weak.append({**ref, "why": e.get("why")})
    return {"missing": missing, "weak": weak}


def papers_not_looked_at(db: Session, profile: TargetProfile) -> list[dict[str, Any]]:
    """Past papers of the exam's course (not archived or removed) that the analysis neither read nor left out on the
    learner's word (owner 2026-11-25: an analysis read one photo and missed four)."""
    target = db.get(StudyTarget, profile.target_id)
    if target is None:
        return []
    covered = _covered(profile)
    rows = db.scalars(
        select(Source)
        .where(
            Source.course_id == target.course_id,
            Source.category == "past_paper",
            Source.deleted_at.is_(None),
            Source.archived_at.is_(None),
        )
        .order_by(Source.filename)
    )
    return [{"id": str(s.id), "filename": s.filename} for s in rows if str(s.id) not in covered]


def profile_view(db: Session, profile: TargetProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    src = db.get(Source, profile.source_id) if profile.source_id else None
    if profile.version < 2:
        confirmation = "before_confirmation"
    else:
        confirmation = "confirmed" if profile.confirmed_at is not None else "unconfirmed"
    return {
        "id": str(profile.id),
        "source_id": str(profile.source_id) if profile.source_id else None,
        # The old paper the analysis came from, when it is in RecallSpring (None: it was only shared in a chat).
        "source": (
            {"id": str(src.id), "filename": src.filename, "removed": src.deleted_at is not None}
            if src is not None
            else None
        ),
        "item_types": profile.item_types,
        "bloom_mix": profile.bloom_mix,
        "topic_weights": profile.topic_weights,
        "example_items": profile.example_items,
        "notes": profile.notes,
        "derived_by": profile.model or "assistant",
        "created_at": profile.created_at.isoformat(),
        "version": profile.version,
        # v2 (ADR-013): topics with points/share, concepts, place on the paper, papers, computed share and weight
        "topics": profile.topics,
        # Each paper with its first file (source) and every file of it (files: a paper may be several photos).
        "papers": [
            {
                **p,
                "source": _source_ref(db, p.get("source_id")),
                "files": _paper_files(db, p),
            }
            for p in profile.papers
            if isinstance(p, dict)
        ],
        # Past papers left out on the learner's word, and those of the course the analysis has not looked at.
        "skipped_papers": [
            {**s, "source": _source_ref(db, s.get("source_id"))}
            for s in profile.skipped_papers or []
            if isinstance(s, dict)
        ],
        "not_looked_at": papers_not_looked_at(db, profile),
        # Files without a stated reason they belong to their paper (only analyses since 2026-11-25 state one).
        "evidence_missing": evidence_gaps(db, profile)["missing"] if profile.version >= 2 else [],
        "unreadable": profile.unreadable,
        # confirmed / unconfirmed, or before_confirmation for analyses made before ADR-013
        "confirmation": confirmation,
        "confirmed_at": profile.confirmed_at.isoformat() if profile.confirmed_at else None,
        "confirmed_via": profile.confirmed_via,
    }


def link_profile_source(
    db: Session, user: User, target_id: uuid.UUID, source_id: uuid.UUID | None, request_id: str
) -> StudyTarget:
    """Say which old paper in the course's material the latest exam-style analysis came from (or unlink it). Only the
    link changes; the analysis itself stays as the assistant wrote it. Audited."""
    target = owned(db, StudyTarget, target_id, user.id)
    if target.deleted_at is not None:
        raise ApiError(404, "not_found", "Study target not found.")
    profile = latest_profile(db, target.id)
    if profile is None:
        raise ApiError(404, "no_profile", "This exam has no analysis of an old paper yet.")
    if source_id is not None:
        src = owned(db, Source, source_id, user.id)
        if src.course_id != target.course_id or src.deleted_at is not None:
            raise ApiError(422, "source_not_in_course", "Choose a file from this course's material.")
    if profile.source_id != source_id:
        audit(
            db,
            actor_id=user.id,
            action="exam_profile.source_linked",
            target_type="target_profile",
            target_id=profile.id,
            details={
                "from": str(profile.source_id) if profile.source_id else None,
                "to": str(source_id) if source_id else None,
            },
            request_id=request_id,
        )
        profile.source_id = source_id
        if profile.version >= 2:
            # the first paper of a v2 analysis is the one the link shows
            papers = [dict(p) for p in profile.papers if isinstance(p, dict)] or [{"label": None}]
            papers[0]["source_id"] = str(source_id) if source_id else None
            profile.papers = papers
        db.flush()
    return target


BEFORE_EXAM_LABELS = {
    "regular": "Regular reviews only",
    "extra_review": "An extra review before the exam",
    "intense": "Intense",
}


def before_exam_view(target: StudyTarget) -> dict[str, Any]:
    """The "Before this exam" choice in words (ADR-014 §4); never shown as a chance of remembering."""
    choice = before_exam_choice(exam_target(target.goal, target.exam_retention))
    return {
        "choice": choice,
        "label": BEFORE_EXAM_LABELS[choice],
        "goal_default": before_exam_choice(exam_target(target.goal, None)),
        "chosen": target.exam_retention is not None,
    }


def _before_exam_name(target: StudyTarget) -> str:
    return "default" if target.exam_retention is None else before_exam_choice(float(target.exam_retention))


def target_view(db: Session, target: StudyTarget, today: date) -> dict[str, Any]:
    return {
        "id": str(target.id),
        "kind": target.kind,
        "name": target.name,
        "due_date": target.due_date.isoformat(),
        "days_left": (target.due_date - today).days,
        "status": target.status,
        "result": target.result,
        "goal": target.goal,
        "before_exam": before_exam_view(target),
        "scope_description": target.scope_description,
        "scope": scope_view(db, target),
        "notes": target.notes,
        "concepts_in_scope": len(scope_concepts(db, target)),
        "profile": profile_view(db, latest_profile(db, target.id)),
    }


def _explain_plan(db: Session, course: Course, active: StudyTarget | None) -> dict[str, Any] | None:
    """Whether the assistant should show "Why this plan" without being asked (ADR-013 §3): at the first study session
    for this exam and after its analysis changed, i.e. when no session of this course was finished since then.
    Otherwise only when the learner asks."""
    if active is None:
        return None

    def finished_since(when: datetime) -> bool:
        found = db.scalar(
            select(StudySession.id)
            .where(
                StudySession.course_id == course.id,
                StudySession.ended_at.is_not(None),
                StudySession.started_at >= when,
            )
            .limit(1)
        )
        return found is not None

    profile = latest_profile(db, active.id)
    since = max(active.created_at, profile.created_at) if profile else active.created_at
    if finished_since(since):
        return {"now": False, "why": "Only when the learner asks why, or asks about the plan."}
    changed = profile is not None and finished_since(active.created_at)
    return {
        "now": True,
        "why": "The exam analysis changed since the last session." if changed else "First study session for this exam.",
        "how": "Call get_plan_rationale (ChatGPT in Chat: get_exam_readiness with why=true) and explain it in a few "
        "lines before you start.",
    }


def study_context(db: Session, course: Course, today: date, style_percent: int = 75) -> dict[str, Any]:
    """Everything Claude needs at the start of a study session in one course, including whether to ask the
    learner what they are preparing for."""
    if course.kind == "interest":
        return _interest_context(db, course, today)
    targets = live_targets(db, course.id)
    active = active_target(targets, today)
    stale = [t for t in targets if t.status == "upcoming" and t.due_date < today]
    passed = [t for t in targets if t.status == "passed"]
    reasons = []
    if active is None:
        reasons.append("no upcoming target is set for this course")
    if stale:
        reasons.append(
            "a target date has passed; ask whether it was passed, failed or moved: " + ", ".join(t.name for t in stale)
        )
    quizzes = db.scalars(select(Quiz).where(Quiz.course_id == course.id).order_by(Quiz.created_at.desc()).limit(5))
    return {
        "course": {"id": str(course.id), "title": course.title, "kind": course.kind},
        "today": today.isoformat(),
        "active_target": target_view(db, active, today) if active else None,
        "other_targets": [target_view(db, t, today) for t in targets if t is not active],
        "passed_targets": [t.name for t in passed],
        "needs_setup": bool(reasons),
        "setup_reasons": reasons,
        "ask_learner": SETUP_QUESTIONS if active is None else [],
        "recent_simulations": [
            {
                "quiz_id": str(q.id),
                "title": q.title,
                "status": q.status,
                "submitted_at": q.submitted_at.isoformat() if q.submitted_at else None,
            }
            for q in quizzes
        ],
        "learning": _learning_counts(db, active) if active else None,
        "explain_plan": _explain_plan(db, course, active),
        # Every past paper of the course (owner 2026-11-25): an analysis looks at each one or leaves it out on the
        # learner's word; photos of one paper may be several files.
        "past_papers": [
            {"id": str(s.id), "filename": s.filename, "kind": s.kind}
            for s in db.scalars(
                select(Source)
                .where(
                    Source.course_id == course.id,
                    Source.category == "past_paper",
                    Source.deleted_at.is_(None),
                    Source.archived_at.is_(None),
                )
                .order_by(Source.filename)
            )
        ],
        "rules": [
            "Learn first: concepts that are not_studied are taught (explain each part completely and concretely, "
            "then the learner summarises in the summary form) before any practice or simulation. RecallSpring "
            "refuses practice on unstudied concepts unless the learner says they already know them or asks for a "
            "diagnostic pre-test. Never assume the learner studied something that is not studied or known here, "
            "or that you did not teach in this conversation.",
            "Material of passed targets is in maintenance: keep reviewing it, but give priority to the active target.",
            f"About {style_percent} % of practice questions follow the style of the target's exam profile (past "
            f"papers); the other {100 - style_percent} % are deeper Bloom 4-5 questions for understanding.",
        ],
    }


def _interest_context(db: Session, course: Course, today: date) -> dict[str, Any]:
    """A personal interest: no exams; the learner's goal (the course description) drives the session."""
    from .interests import INTEREST_QUESTIONS
    from .learning import effective_status

    goal = (course.description or "").strip()
    concepts = list(db.scalars(select(Concept).where(Concept.course_id == course.id, Concept.deleted_at.is_(None))))
    practised = set(
        db.scalars(select(ReviewState.concept_id).where(ReviewState.concept_id.in_([c.id for c in concepts])))
    )
    counts = {"not_studied": 0, "studied": 0, "known": 0}
    for concept in concepts:
        counts[effective_status(concept, concept.id in practised)] += 1
    quizzes = db.scalars(select(Quiz).where(Quiz.course_id == course.id).order_by(Quiz.created_at.desc()).limit(5))
    return {
        "course": {"id": str(course.id), "title": course.title, "kind": "interest"},
        "today": today.isoformat(),
        "goal": goal or None,
        "focus_until": course.focus_until.isoformat() if course.focus_until and course.focus_until >= today else None,
        "active_target": None,
        "other_targets": [],
        "passed_targets": [],
        "needs_setup": not goal,
        "setup_reasons": [] if goal else ["no goal is set for this interest"],
        "ask_learner": [] if goal else INTEREST_QUESTIONS,
        "recent_simulations": [
            {
                "quiz_id": str(q.id),
                "title": q.title,
                "status": q.status,
                "submitted_at": q.submitted_at.isoformat() if q.submitted_at else None,
            }
            for q in quizzes
        ],
        "learning": counts,
        "rules": [
            "This is a personal interest, not a university course: there is no exam and no deadline. Work toward "
            "the learner's goal; save it with set_interest_goal when it is missing or changes.",
            "Learn first still applies: teach material that is not_studied (explain each part completely and "
            "concretely, then the learner summarises in the summary form) before practice; never assume it was "
            "studied. Prefer applied exercises, small projects and real data (Bloom "
            "3-6) over exam-style questions.",
            "University comes first unless the learner chose otherwise: get_study_plan shows how much time the "
            "interests get today. Set a focus (set_focus) or a share of the day (set_availability interest_percent) "
            "only when the learner clearly asks for it.",
        ],
    }


def _learning_counts(db: Session, target: StudyTarget) -> dict[str, int]:
    from .learning import effective_status

    ids = scope_concepts(db, target)
    counts = {"not_studied": 0, "studied": 0, "known": 0}
    if not ids:
        return counts
    practised = set(db.scalars(select(ReviewState.concept_id).where(ReviewState.concept_id.in_(ids))))
    for concept in db.scalars(select(Concept).where(Concept.id.in_(ids))):
        counts[effective_status(concept, concept.id in practised)] += 1
    return counts


# ---------------------------------------------------------------- writes shared by Claude (connector) and the web app


def scope_rows(
    db: Session, user_id: uuid.UUID, course_id: uuid.UUID, items: list[TargetScopeItem]
) -> list[StudyTargetScope]:
    rows = []
    for item in items:
        if item.kind in ("source", "pages"):
            src = db.get(Source, item.source_id) if item.source_id else None
            if src is None or src.user_id != user_id or src.course_id != course_id or src.deleted_at:
                raise ApiError(422, "invalid_scope", "A scope entry refers to a source that is not in this course.")
            if item.kind == "pages" and (
                item.page_from is None or item.page_to is None or item.page_from > item.page_to
            ):
                raise ApiError(422, "invalid_scope", "A page range needs page_from <= page_to.")
        elif item.kind == "topic":
            topic = db.get(SyllabusItem, item.topic_id) if item.topic_id else None
            if topic is None or topic.user_id != user_id or topic.course_id != course_id:
                raise ApiError(422, "invalid_scope", "A scope entry refers to a topic that is not in this course.")
        else:
            concept = db.get(Concept, item.concept_id) if item.concept_id else None
            if concept is None or concept.user_id != user_id or concept.course_id != course_id:
                raise ApiError(422, "invalid_scope", "A scope entry refers to a concept that is not in this course.")
        rows.append(
            StudyTargetScope(
                kind=item.kind,
                source_id=item.source_id,
                page_from=item.page_from,
                page_to=item.page_to,
                syllabus_item_id=item.topic_id,
                concept_id=item.concept_id,
            )
        )
    return rows


def normalise(name: str) -> str:
    """Case-, space- and punctuation-insensitive form of a name ("1. Kolokvij " == "1 kolokvij")."""
    return "".join(ch for ch in name.casefold() if ch.isalnum())


def is_same_exam(a: StudyTarget, name: str, kind: str, due: date) -> bool:
    """Two records describe the same exam when the names match, or the type and the date match."""
    return normalise(a.name) == normalise(name) or (a.kind == kind and a.due_date == due)


def find_duplicate(
    db: Session, course_id: uuid.UUID, name: str, kind: str, due: date, exclude: uuid.UUID | None = None
) -> StudyTarget | None:
    for t in live_targets(db, course_id):
        if t.id != exclude and t.status != "cancelled" and is_same_exam(t, name, kind, due):
            return t
    return None


def duplicate_groups(targets: list[StudyTarget]) -> dict[uuid.UUID, list[uuid.UUID]]:
    """For each live target, the other targets of the same course that look like the same exam."""
    out: dict[uuid.UUID, list[uuid.UUID]] = {}
    for a in targets:
        if a.status == "cancelled":
            continue
        for b in targets:
            if b.id != a.id and b.course_id == a.course_id and b.status != "cancelled":
                if is_same_exam(b, a.name, a.kind, a.due_date):
                    out.setdefault(a.id, []).append(b.id)
    return out


def _follow_exam(db: Session, user: User, course_id: uuid.UUID) -> None:
    """Review dates follow a changed exam (ADR-014 exam layer)."""
    from .reviews import recompute_course  # reviews imports this module lazily too

    recompute_course(db, user, course_id, clock.now())


def _brief(t: StudyTarget) -> dict[str, Any]:
    return {"id": str(t.id), "name": t.name, "kind": t.kind, "due_date": t.due_date.isoformat(), "status": t.status}


def create_target(db: Session, user: User, payload: TargetIn, request_id: str, *, origin: str) -> StudyTarget:
    course = owned(db, Course, payload.course_id, user.id, for_update=True)  # serialises parallel chats
    from .interests import refuse_interest_exam

    refuse_interest_exam(course)
    existing = find_duplicate(db, course.id, payload.name, payload.kind, payload.due_date)
    if existing is not None:
        raise ApiError(
            409,
            "target_exists",
            f"{course.title} already has {existing.name} on {existing.due_date.isoformat()} "
            f"(target_id {existing.id}). Update that one instead of adding it again.",
            {"existing": _brief(existing)},
        )
    target = StudyTarget(
        user_id=user.id,
        course_id=payload.course_id,
        kind=payload.kind,
        name=payload.name,
        due_date=payload.due_date,
        scope_description=payload.scope_description,
        notes=payload.notes,
        goal=payload.goal,
        exam_retention=BEFORE_EXAM.get(payload.before_exam),
    )
    db.add(target)
    db.flush()
    for row in scope_rows(db, user.id, payload.course_id, payload.scope):
        row.target_id = target.id
        db.add(row)
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="target.created",
        target_type="study_target",
        target_id=target.id,
        details={
            "name": payload.name,
            "due_date": payload.due_date.isoformat(),
            "origin": origin,
            **({"before_exam": payload.before_exam} if payload.before_exam != "default" else {}),
        },
        request_id=request_id,
    )
    _follow_exam(db, user, target.course_id)
    return target


def update_target(
    db: Session, user: User, target_id: uuid.UUID, payload: TargetUpdateIn, request_id: str, *, origin: str
) -> StudyTarget:
    """Move a date, rename, mark passed/failed, or refine the scope. Audited; nothing is deleted."""
    target = db.get(StudyTarget, target_id, with_for_update=True)
    if target is None or target.user_id != user.id or target.deleted_at is not None:
        raise ApiError(404, "not_found", "Study target not found.")
    changes: dict[str, Any] = {}
    for key in ("name", "kind", "goal", "due_date", "status", "result", "scope_description", "notes"):
        value = getattr(payload, key)
        if value is not None and value != getattr(target, key):
            changes[key] = {"from": str(getattr(target, key)), "to": str(value)}
            setattr(target, key, value)
    if payload.before_exam is not None:
        retention = BEFORE_EXAM.get(payload.before_exam)  # "default" = NULL, the goal's default
        if retention != (None if target.exam_retention is None else float(target.exam_retention)):
            changes["before_exam"] = {"from": _before_exam_name(target), "to": payload.before_exam}
            target.exam_retention = retention
    if payload.scope is not None:
        new_rows = scope_rows(db, user.id, target.course_id, payload.scope)
        for old in db.scalars(select(StudyTargetScope).where(StudyTargetScope.target_id == target.id)):
            db.delete(old)  # scope rows are a derived index of the learner's description, not learning evidence
        for row in new_rows:
            row.target_id = target.id
            db.add(row)
        changes["scope"] = {"entries": len(new_rows)}
    target.revision += 1
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="target.updated",
        target_type="study_target",
        target_id=target.id,
        details={**changes, "origin": origin},
        request_id=request_id,
    )
    if changes:
        _follow_exam(db, user, target.course_id)
    return target


def _owned_target(db: Session, user: User, target_id: uuid.UUID, *, deleted: bool = False) -> StudyTarget:
    target = db.get(StudyTarget, target_id, with_for_update=True)
    if target is None or target.user_id != user.id or (target.deleted_at is not None) != deleted:
        raise ApiError(404, "not_found", "Study target not found.")
    return target


def delete_target(db: Session, user: User, target_id: uuid.UUID, request_id: str, now: Any) -> StudyTarget:
    """Soft delete: hidden from plans, the timeline and Claude; restorable. Simulations and answers are kept."""
    target = _owned_target(db, user, target_id)
    target.deleted_at = now
    target.revision += 1
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="target.deleted",
        target_type="study_target",
        target_id=target.id,
        details=_brief(target),
        request_id=request_id,
    )
    _follow_exam(db, user, target.course_id)
    return target


def restore_target(db: Session, user: User, target_id: uuid.UUID, request_id: str) -> StudyTarget:
    target = _owned_target(db, user, target_id, deleted=True)
    target.deleted_at = None
    target.revision += 1
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="target.restored",
        target_type="study_target",
        target_id=target.id,
        details=_brief(target),
        request_id=request_id,
    )
    _follow_exam(db, user, target.course_id)
    return target


def merge_targets(
    db: Session, user: User, source_id: uuid.UUID, into_id: uuid.UUID, request_id: str, now: Any
) -> StudyTarget:
    """Fold a duplicate into the target to keep: its exam profiles and simulations move over, its scope mapping is
    used when the kept one has none, and its own words are added to the kept one's notes. The duplicate is then
    soft-deleted (restorable)."""
    if source_id == into_id:
        raise ApiError(422, "same_target", "Choose two different exams to merge.")
    source = _owned_target(db, user, source_id)
    into = _owned_target(db, user, into_id)
    if source.course_id != into.course_id:
        raise ApiError(422, "different_courses", "Only exams of the same course can be merged.")
    moved_profiles = 0
    for profile in db.scalars(select(TargetProfile).where(TargetProfile.target_id == source.id)):
        profile.target_id = into.id
        moved_profiles += 1
    moved_quizzes = 0
    for quiz in db.scalars(select(Quiz).where(Quiz.target_id == source.id)):
        quiz.target_id = into.id
        moved_quizzes += 1
    copied_scope = 0
    if db.scalar(select(StudyTargetScope.id).where(StudyTargetScope.target_id == into.id).limit(1)) is None:
        for row in db.scalars(select(StudyTargetScope).where(StudyTargetScope.target_id == source.id)):
            db.add(
                StudyTargetScope(
                    target_id=into.id,
                    kind=row.kind,
                    source_id=row.source_id,
                    page_from=row.page_from,
                    page_to=row.page_to,
                    syllabus_item_id=row.syllabus_item_id,
                    concept_id=row.concept_id,
                )
            )
            copied_scope += 1
    # Text already kept (e.g. merged, restored and merged again) is not appended twice.
    kept_text = f"{into.scope_description}\n{into.notes or ''}"
    extra = []
    scope, notes = source.scope_description.strip(), (source.notes or "").strip()
    if scope and scope != into.scope_description.strip() and scope not in kept_text:
        extra.append(f"Scope (from {source.name}): {scope}")
    if notes and notes not in kept_text:
        extra.append(f"Notes (from {source.name}): {notes}")
    if extra:
        into.notes = "\n\n".join([*(p for p in [into.notes] if p), *extra])[:4000]
    into.revision += 1
    source.deleted_at = now
    source.revision += 1
    db.flush()
    audit(
        db,
        actor_id=user.id,
        action="target.merged",
        target_type="study_target",
        target_id=into.id,
        details={
            "merged": _brief(source),
            "profiles_moved": moved_profiles,
            "simulations_moved": moved_quizzes,
            "scope_rows_copied": copied_scope,
        },
        request_id=request_id,
    )
    _follow_exam(db, user, into.course_id)
    return into
