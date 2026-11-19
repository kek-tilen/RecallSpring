"""Owner administration CLI. There is no public sign-up: the single owner account is created here.

recallspring create-owner --username <name>      (password is prompted, never passed as an argument)
recallspring seed-demo --username <name>         (adds a clearly labelled demo course)
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select

from . import clock
from .db import new_session
from .models import Concept, Course, Question, QuestionConcept, SyllabusItem, User
from .security import hash_password
from .services.events import audit

DEMO_TITLE = "Demo — Cellular respiration (sample data)"


def create_owner(username: str) -> int:
    password = getpass.getpass("New password (min 12 characters): ")
    if len(password) < 12:
        print("Password must have at least 12 characters.", file=sys.stderr)
        return 2
    if getpass.getpass("Repeat password: ") != password:
        print("Passwords do not match.", file=sys.stderr)
        return 2
    with new_session() as db:
        if db.scalar(select(User).where(User.username == username)):
            print(f"User {username!r} already exists.", file=sys.stderr)
            return 1
        user = User(username=username, password_hash=hash_password(password))
        db.add(user)
        db.flush()
        audit(db, actor_id=user.id, action="user.created", target_type="user", target_id=user.id)
        db.commit()
    print(f"Owner account {username!r} created.")
    return 0


def seed_demo(username: str) -> int:
    with new_session() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            print(f"User {username!r} not found. Run create-owner first.", file=sys.stderr)
            return 1
        if db.scalar(select(Course).where(Course.user_id == user.id, Course.title == DEMO_TITLE)):
            print("Demo course already exists.")
            return 0
        course = Course(
            user_id=user.id, title=DEMO_TITLE, description="Labelled demo data for trying RecallSpring. Safe to delete."
        )
        db.add(course)
        db.flush()
        topic = SyllabusItem(user_id=user.id, course_id=course.id, title="Energy release in cells", position=0)
        db.add(topic)
        db.flush()
        concepts = {
            "Glycolysis": "Splits glucose into two pyruvate molecules in the cytoplasm, yielding a small net ATP "
            "gain and NADH.",
            "Citric acid cycle": "Oxidises acetyl-CoA in the mitochondrial matrix, producing CO2, NADH and FADH2.",
            "Oxidative phosphorylation": "Uses the electron transport chain and a proton gradient to produce "
            "most of the ATP.",
        }
        rows = {}
        for term, definition in concepts.items():
            c = Concept(
                user_id=user.id,
                course_id=course.id,
                syllabus_item_id=topic.id,
                term=term,
                definition_draft=definition,
                source_confidence="inferred",
            )
            db.add(c)
            rows[term] = c
        db.flush()
        q = Question(
            user_id=user.id,
            course_id=course.id,
            bloom_level=4,
            prompt="Compare glycolysis and the citric acid cycle: where does each happen, what goes in, and "
            "what does each contribute to the cell's ATP supply?",
            rubric={
                "expected_points": [
                    "Glycolysis happens in the cytoplasm; the citric acid cycle in the mitochondrial matrix",
                    "Glycolysis starts from glucose; the cycle oxidises acetyl-CoA from pyruvate",
                    "Both produce reduced carriers (NADH, FADH2) that feed oxidative phosphorylation",
                ]
            },
            source_refs=[],
            provenance={"origin": "demo_seed"},
            created_at=clock.now(),
        )
        db.add(q)
        db.flush()
        for term in ("Glycolysis", "Citric acid cycle"):
            db.add(QuestionConcept(question_id=q.id, concept_id=rows[term].id))
        db.commit()
    print(f"Demo course created: {DEMO_TITLE}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recallspring")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create-owner", "seed-demo"):
        p = sub.add_parser(name)
        p.add_argument("--username", required=True)
    args = parser.parse_args(argv)
    if args.command == "create-owner":
        return create_owner(args.username)
    return seed_demo(args.username)


if __name__ == "__main__":
    raise SystemExit(main())
