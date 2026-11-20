"""Owner administration CLI. There is no public sign-up: the single owner account is created here.

recallspring create-owner --username <name>      (password is prompted, never passed as an argument)
recallspring seed-demo --username <name>         (adds a clearly labelled demo course)
recallspring worker [--once]                     (processes source extraction jobs; no model calls)
recallspring connector-token --username <name>   (writes a Claude connector token to a private file)
recallspring backup [--if-due]                   (database + uploaded files, checked by a test restore)
recallspring backup-status                       (last backup, kept snapshots, location)
recallspring backup-restore --database <new> [--snapshot <name>|latest] [--storage <empty folder>]
                                                 (restores into a NEW database / folder; never overwrites)
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

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


def default_token_file() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "RecallSpring" if base else Path.home() / ".config" / "recallspring"
    return root / "connector-token"


def connector_token(username: str, label: str, path: Path) -> int:
    """Create a connector token and write it to a private file; the token is never printed."""
    from .api.settings import issue_token

    with new_session() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            print(f"User {username!r} not found. Run create-owner first.", file=sys.stderr)
            return 1
        _, token = issue_token(db, user.id, label)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token)
        os.replace(tmp, path)
        db.commit()
    print(f"Connector token '{label}' written to {path}")
    print("Revoke it any time in RecallSpring settings (or create a new one with this command).")
    return 0


def _size(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


def backup_now(if_due: bool) -> int:
    from . import backup

    if if_due and not backup.due():
        print("No backup due.")
        return 0
    try:
        view = backup.run("cli")
    except backup.BackupError as exc:
        print(f"Backup failed ({exc.code}): {exc.message}", file=sys.stderr)
        return 1
    last = view["last"]
    print(f"Backup {last['snapshot']} (UTC) in {view['location']}")
    print(f"  database: {last['tables']} tables, {last['rows']} rows, dump {_size(last['dump_bytes'])}")
    print(f"  files: {last['files']} ({last['files_copied']} new), {_size(last['files_bytes'])}")
    if last["files_missing"]:
        print(f"  WARNING: {last['files_missing']} uploaded file(s) were missing from storage")
    print(f"  check: {last['check']}; kept snapshots: {len(view['snapshots'])}; removed: {last['removed_snapshots']}")
    return 0


def backup_status() -> int:
    from . import backup

    view = backup.status_view()
    print(f"Backups {'on' if view['enabled'] else 'OFF'}, every {view['interval_hours']} h, in {view['location']}")
    if view["same_disk_as_storage"]:
        print("  Same disk as the uploaded files: set RS_BACKUP_DIR to another disk or a synced folder.")
    print(f"  last good: {view['last_success_at'] or 'never'}; next due: {view['next_due']}")
    if view["last_error"]:
        print(f"  LAST ATTEMPT FAILED ({view['last_error']['code']}): {view['last_error']['message']}")
    print(f"  snapshots (UTC, newest first): {', '.join(view['snapshots']) or 'none'}; {_size(view['disk_bytes'])}")
    print(f"  tools: {view['tools'] or 'pg_dump not found'}")
    return 0


def backup_restore(snapshot: str, database: str, storage: Path | None) -> int:
    from . import backup

    try:
        result = backup.restore(snapshot, database, storage)
    except backup.BackupError as exc:
        print(f"Restore refused or failed ({exc.code}): {exc.message}", file=sys.stderr)
        return 1
    print(f"Restored backup {result['snapshot']} into the new database {result['database']} ({result['rows']} rows).")
    if result["tables_differing"]:
        print(f"  WARNING: row counts differ in {', '.join(result['tables_differing'])}", file=sys.stderr)
    if result["storage"]:
        print(f"  {result['files']} of {result['files_expected']} files copied to {result['storage']}")
    print("Nothing was switched. To use it, stop RecallSpring, then in services/api/.env set")
    print(f"  RS_DATABASE_URL={result['database_url']}  (keep your password in place of ***)")
    if result["storage"]:
        print(f"  RS_STORAGE_DIR={result['storage']}")
    print("run `alembic upgrade head` and start RecallSpring again. Keep the old database until you are sure.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recallspring")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create-owner", "seed-demo"):
        p = sub.add_parser(name)
        p.add_argument("--username", required=True)
    token = sub.add_parser("connector-token")
    token.add_argument("--username", required=True)
    token.add_argument("--label", default="Claude Desktop")
    token.add_argument("--file", type=Path, default=default_token_file(), help="where the token is written")
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true", help="process queued jobs, then exit")
    bk = sub.add_parser("backup", help="back up the database and uploaded files now")
    bk.add_argument("--if-due", action="store_true", help="only when the last good backup is older than the interval")
    sub.add_parser("backup-status", help="show the last backup and the kept snapshots")
    rs = sub.add_parser("backup-restore", help="restore a backup into a NEW database (never overwrites)")
    rs.add_argument("--snapshot", default="latest", help="snapshot name (see backup-status) or 'latest'")
    rs.add_argument("--database", required=True, help="name of a database that does not exist yet")
    rs.add_argument("--storage", type=Path, help="an empty or new folder for the uploaded files")
    args = parser.parse_args(argv)
    if args.command in ("backup", "backup-status", "backup-restore"):
        import logging

        logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
        if args.command == "backup":
            return backup_now(args.if_due)
        if args.command == "backup-status":
            return backup_status()
        return backup_restore(args.snapshot, args.database, args.storage)
    if args.command == "create-owner":
        return create_owner(args.username)
    if args.command == "connector-token":
        return connector_token(args.username, args.label, args.file)
    if args.command == "worker":
        import logging

        from .ingest.jobs import run_pending, run_worker

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
        if args.once:
            print(f"Processed {run_pending()} job(s).")
        else:
            run_worker()
        return 0
    return seed_demo(args.username)


if __name__ == "__main__":
    raise SystemExit(main())
