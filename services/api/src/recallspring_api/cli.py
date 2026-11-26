"""Owner administration CLI. There is no public sign-up: the single owner account is created here.

recallspring create-owner --username <name>      (password is prompted, never passed as an argument)
recallspring seed-demo --username <name>         (adds a clearly labelled demo course)
recallspring worker [--once]                     (processes source extraction jobs; no model calls)
recallspring connector-token --username <name> [--client codex|antigravity]
                                                 (writes a connector token to a private file)
recallspring backup [--if-due]                   (database + uploaded files, checked by a test restore)
recallspring backup-status                       (last backup, kept snapshots, location)
recallspring backup-restore --database <new> [--snapshot <name>|latest] [--storage <empty folder>]
                                                 (restores into a NEW database / folder; never overwrites)
recallspring recompute-reviews                   (replays every review state with the current scheduler policy;
                                                 a derived cache, evidence untouched, no model calls)
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


def create_owner(username: str, timezone: str | None = None) -> int:
    from .config import get_settings
    from .services import timezones

    zone = timezone or get_settings().default_timezone
    if zone not in timezones.names():
        print(f"Unknown time zone {zone!r} (use an IANA name such as Europe/Ljubljana).", file=sys.stderr)
        return 2
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
        user = User(username=username, password_hash=hash_password(password), timezone=zone)
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


def default_token_file(client: str = "claude") -> Path:
    """Claude Desktop, Codex and Antigravity each get their own file, so revoking one never disconnects another."""
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "RecallSpring" if base else Path.home() / ".config" / "recallspring"
    return root / ("connector-token" if client == "claude" else f"{client}-connector-token")


def connector_token(username: str, label: str | None, path: Path, client: str = "claude") -> int:
    """Create a connector token and write it to a private file; the token is never printed."""
    from .api.settings import issue_token

    with new_session() as db:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            print(f"User {username!r} not found. Run create-owner first.", file=sys.stderr)
            return 1
        row, token = issue_token(db, user.id, label, client)
        written_label = row.label
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token)
        os.replace(tmp, path)
        db.commit()
    print(f"Connector token '{written_label}' written to {path}")
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


def recompute_reviews() -> int:
    """Replay every review state with the current scheduler policy, e.g. once after a new policy version (ADR-014:
    the exam layer of rs-interval-v3 applies to concepts practised before it). Review states are a derived cache:
    the evidence is not touched, and the same evidence always gives the same schedule. Audited per account."""
    from .learning.scheduler import POLICY_VERSION
    from .models import ReviewState
    from .services.reviews import recompute

    now = clock.now()
    total = changed = 0
    with new_session() as db:
        for user in db.scalars(select(User).order_by(User.created_at)).all():
            before = {
                r.concept_id: (r.due_at, r.due_reason.get("code"))
                for r in db.scalars(select(ReviewState).where(ReviewState.user_id == user.id))
            }
            if not before:
                continue
            after = recompute(db, user, sorted(before, key=str), now)
            moved = sum(1 for cid, s in after.items() if s is None or (s.due_at, s.reason.code) != before[cid])
            audit(
                db,
                actor_id=user.id,
                action="reviews.recomputed",
                target_type="user",
                target_id=user.id,
                details={"policy_version": POLICY_VERSION, "states": len(before), "changed": moved},
            )
            total += len(before)
            changed += moved
        db.commit()
    print(f"Replayed {total} review state(s) with {POLICY_VERSION}; {changed} got a new date or reason.")
    return 0


def serve_api(host: str, port: int, log_file: Path | None) -> int:
    """scripts/start-local.ps1 runs this without a window, logging to local-data/logs/api.log."""
    import uvicorn

    from . import runtime

    if log_file is None:
        uvicorn.run("recallspring_api.main:app", host=host, port=port)
    else:
        runtime.log_to_file(log_file)
        # log_config=None keeps uvicorn from installing console handlers; its loggers reach the file.
        uvicorn.run("recallspring_api.main:app", host=host, port=port, log_config=None)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recallspring")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create-owner", "seed-demo"):
        p = sub.add_parser(name)
        p.add_argument("--username", required=True)
        if name == "create-owner":
            p.add_argument("--timezone", help="IANA time zone, e.g. Europe/Ljubljana (default: RS_DEFAULT_TIMEZONE)")
    token = sub.add_parser("connector-token")
    token.add_argument("--username", required=True)
    token.add_argument(
        "--client", choices=["claude", "codex", "antigravity"], default="claude", help="which assistant uses it"
    )
    token.add_argument("--label", help='default "Claude Desktop", "Codex" or "Antigravity"')
    token.add_argument("--file", type=Path, help="where the token is written (default: one file per assistant)")
    worker = sub.add_parser("worker")
    worker.add_argument("--once", action="store_true", help="process queued jobs, then exit")
    worker.add_argument("--log-file", type=Path, help="log to this rotating file instead of the console")
    serve = sub.add_parser("serve", help="run the API (and the built web app) on 127.0.0.1")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=4318)
    serve.add_argument("--log-file", type=Path, help="log to this rotating file instead of the console")
    bk = sub.add_parser("backup", help="back up the database and uploaded files now")
    bk.add_argument("--if-due", action="store_true", help="only when the last good backup is older than the interval")
    sub.add_parser("backup-status", help="show the last backup and the kept snapshots")
    rs = sub.add_parser("backup-restore", help="restore a backup into a NEW database (never overwrites)")
    rs.add_argument("--snapshot", default="latest", help="snapshot name (see backup-status) or 'latest'")
    rs.add_argument("--database", required=True, help="name of a database that does not exist yet")
    rs.add_argument("--storage", type=Path, help="an empty or new folder for the uploaded files")
    sub.add_parser("recompute-reviews", help="replay every review state with the current scheduler policy")
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
        return create_owner(args.username, args.timezone)
    if args.command == "connector-token":
        return connector_token(args.username, args.label, args.file or default_token_file(args.client), args.client)
    if args.command == "serve":
        return serve_api(args.host, args.port, args.log_file)
    if args.command == "recompute-reviews":
        return recompute_reviews()
    if args.command == "worker":
        import logging

        from . import runtime
        from .ingest.jobs import run_pending, run_worker

        if args.log_file:
            runtime.log_to_file(args.log_file)
        else:
            logging.basicConfig(level=logging.INFO, format=runtime.LOG_FORMAT)
        if args.once:
            print(f"Processed {run_pending()} job(s).")
        else:
            run_worker()
        return 0
    return seed_demo(args.username)


if __name__ == "__main__":
    raise SystemExit(main())
