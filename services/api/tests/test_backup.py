"""Backups (backup.py, docs/08 -> Backups): database + files, checked by a real restore, retention, failures,
restore into a new database. Uses the dev database server's pg_dump (PATH or the dev container)."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, make_url, select, text

from recallspring_api import backup, cli
from recallspring_api.db import new_session
from recallspring_api.ingest.jobs import run_pending, run_worker
from recallspring_api.models import AuditEvent, Source

from .conftest import Api

RESTORED_DB = "recallspring_test_restored"


@pytest.fixture
def backups(settings: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "backups"
    monkeypatch.setattr(settings, "backup_enabled", True)
    monkeypatch.setattr(settings, "backup_dir", root)
    return root


needs_pg_dump = pytest.mark.skipif(backup.find_tools() is None, reason="pg_dump not available (PATH or dev container)")


def _databases() -> set[str]:
    url = make_url(backup.get_settings().database_url)
    engine = create_engine(url.set(database="postgres"))
    try:
        with engine.connect() as conn:
            return {r[0] for r in conn.execute(text("SELECT datname FROM pg_database"))}
    finally:
        engine.dispose()


def _drop(name: str) -> None:
    url = make_url(backup.get_settings().database_url)
    engine = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        engine.dispose()


def _upload(api: Api, content: bytes = b"# Glycolysis\n\nGlucose is split into two pyruvate molecules.\n") -> str:
    course = api.post("/courses", {"title": "Biology 101"}).json()
    assert api.upload(course["id"], "notes.md", content).status_code in (200, 201, 202)
    run_pending()
    with new_session() as db:
        return db.scalar(select(Source.storage_key).where(Source.filename == "notes.md"))


def _actions() -> list[str]:
    with new_session() as db:
        return list(db.scalars(select(AuditEvent.action).where(AuditEvent.action.like("backup.%"))))


@needs_pg_dump
def test_backup_holds_database_and_files_and_is_checked(
    owner_api: Api, backups: Path, frozen: Any, capsys: Any
) -> None:
    key = _upload(owner_api)
    first = owner_api.get("/settings/backup").json()
    assert first["last_success_at"] is None and first["next_due"] == "now" and first["snapshots"] == []
    attention = owner_api.get("/dashboard").json()["attention"]
    assert [a["title"] for a in attention if a["kind"] == "backup"] == ["No backup yet"]

    r = owner_api.post("/settings/backup")
    assert r.status_code == 200, r.text
    view = r.json()
    last = view["last"]
    assert last["check"] == "restored" and last["reason"] == "manual"
    assert last["files"] == 1 and last["files_copied"] == 1 and last["files_missing"] == 0
    assert view["snapshots"] == [last["snapshot"]] and view["last_error"] is None
    assert "postgresql" not in json.dumps(view)  # no database URL (and so no password) in the view

    copy = backups / "files" / key
    assert copy.read_bytes() == (backup.get_settings().storage_dir / key).read_bytes()
    manifest = json.loads((backups / "snapshots" / last["snapshot"] / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["sources"] == 1 and manifest["counts"]["courses"] == 1
    assert manifest["files"]["keys"] == [key] and manifest["check"]["rows"] == last["rows"]
    assert manifest["alembic_version"]
    assert not any(n.endswith(backup.CHECK_SUFFIX) for n in _databases())  # throwaway check database is gone
    assert not [a for a in owner_api.get("/dashboard").json()["attention"] if a["kind"] == "backup"]
    assert _actions() == ["backup.created"]
    row = next(h for h in owner_api.get("/history").json() if h["type"] == "backup.created")
    assert row["text"] == "Backup made" and row["detail"].endswith("files, checked by a test restore")

    # Later the same day: the file is not copied again; only the newest backup of the day is kept.
    frozen.advance(hours=1)
    second = backup.run("cli")["last"]
    assert second["files"] == 1 and second["files_copied"] == 0 and second["removed_snapshots"] == 1
    assert [p.name for p in backup.snapshots()] == [second["snapshot"]] and copy.is_file()

    assert cli.main(["backup-status"]) == 0
    assert second["snapshot"] in capsys.readouterr().out


def _fake_snapshot(root: Path, name: str, key: str) -> None:
    folder = root / "snapshots" / name
    folder.mkdir(parents=True)
    (folder / "db.dump").write_bytes(b"dump")
    (folder / "manifest.json").write_text(json.dumps({"files": {"keys": [key]}}), encoding="utf-8")
    blob = root / "files" / key
    blob.parent.mkdir(parents=True, exist_ok=True)
    blob.write_bytes(name.encode())


def test_retention_keeps_seven_days_and_four_weeks(backups: Path, frozen: Any) -> None:
    frozen.set(datetime(2026, 11, 19, 22, 0, tzinfo=UTC))  # a Thursday
    user = "00000000-0000-4000-8000-000000000001"
    keys: dict[str, str] = {}
    for days_ago in range(40):
        day = datetime(2026, 11, 19) - timedelta(days=days_ago)
        for hour in (3, 21):
            name = day.replace(hour=hour).strftime(backup.STAMP)
            keys[name] = f"{user}/ab/{name.replace('-', '').ljust(64, 'a')}"
            _fake_snapshot(backups, name, keys[name])
    (backups / "recallspring-pre-0009-20261120.dump").write_bytes(b"hand-made")
    (backups / "files" / "README.txt").write_text("not ours", encoding="utf-8")
    (backups / "snapshots" / ".partial-20261101-000000").mkdir()
    (backups / "snapshots" / ".partial-20261119-215900").mkdir()

    removed = backup.prune()

    kept = [p.name for p in backup.snapshots()]
    daily = [f"202611{d}-210000" for d in range(13, 20)]  # newest of each of the last 7 days
    weekly = ["20261101-210000", "20261108-210000"]  # newest of the ISO weeks before (the 2 newest weeks are daily)
    assert kept == sorted(weekly + daily)
    assert removed == 80 - len(kept)
    files = {p.relative_to(backups / "files").as_posix() for p in (backups / "files").rglob("*") if p.is_file()}
    assert files == {keys[n] for n in kept} | {"README.txt"}
    assert (backups / "recallspring-pre-0009-20261120.dump").read_bytes() == b"hand-made"
    assert not (backups / "snapshots" / ".partial-20261101-000000").exists()  # stale leftover of a crash
    assert (backups / "snapshots" / ".partial-20261119-215900").exists()  # may be a backup in progress


def test_unreadable_manifest_keeps_every_file(backups: Path, frozen: Any) -> None:
    key = "00000000-0000-4000-8000-000000000001/ab/" + "a" * 64
    _fake_snapshot(backups, "20261119-100000", key)
    (backups / "snapshots" / "20261119-100000" / "manifest.json").write_text("{", encoding="utf-8")
    orphan = backups / "files" / "00000000-0000-4000-8000-000000000001" / "cd" / ("c" * 64)
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"x")
    backup.prune()
    assert orphan.is_file() and (backups / "files" / key).is_file()


def test_failure_is_reported_without_the_password(
    owner_api: Api, backups: Path, frozen: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    password = make_url(backup.get_settings().database_url).password or "not-set"
    script = f"import sys; sys.stderr.write('FATAL: password authentication failed: {password}\\n'); sys.exit(1)"
    failing = backup.PgTools("bin", [sys.executable, "-c", script], [sys.executable, "-c", script])
    monkeypatch.setattr(backup, "find_tools", lambda: failing)

    r = owner_api.post("/settings/backup")
    assert r.status_code == 503 and r.json()["code"] == "backup_failed"
    assert password not in r.text and "password authentication failed" in r.json()["message"]
    if password != "not-set":
        assert "***" in r.json()["message"]
    view = owner_api.get("/settings/backup").json()
    assert view["last_error"]["code"] == "tool_failed" and password not in json.dumps(view)
    assert view["snapshots"] == []
    assert list((backups / "snapshots").iterdir()) == []  # the half-made snapshot was removed
    item = next(a for a in owner_api.get("/dashboard").json()["attention"] if a["kind"] == "backup")
    assert item["title"] == "The last backup failed" and password not in item["text"]
    assert _actions() == ["backup.failed"]

    assert not backup.due()  # retried after an hour, not in a tight loop
    frozen.advance(minutes=61)
    assert backup.due()


def test_no_pg_dump_is_explained(backups: Path, frozen: Any, settings: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "backup_pg_bin", backups / "no-such-folder")
    with pytest.raises(backup.BackupError) as exc:
        backup.run("cli")
    assert exc.value.code == "no_pg_dump" and "RS_BACKUP_PG_BIN" in exc.value.message
    assert backup.status_view()["tools"] is None


def test_due_follows_the_schedule(backups: Path, frozen: Any, settings: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    assert backup.due()
    backup._write_json(backup._status_path(), {"last_success_at": frozen().isoformat()})  # 16:00 UTC, no account yet
    assert not backup.due() and backup.attention_item() is None
    frozen.set(datetime(2026, 11, 20, 3, 0, tzinfo=UTC))  # daily at 03:00, in UTC before there is an account
    assert backup.due() and backup.attention_item() is None
    frozen.set(datetime(2026, 11, 21, 16, 0, tzinfo=UTC))
    item = backup.attention_item()
    assert item is not None and item["title"] == "No backup for 2 days"
    monkeypatch.setattr(settings, "backup_enabled", False)
    assert not backup.due() and backup.attention_item() is None


def test_worker_checks_for_a_due_backup(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(backup, "run_if_due", lambda: calls.append(1) or False)
    stops = iter([False, True])
    run_worker(poll_seconds=0, should_stop=lambda: next(stops))
    assert calls == [1]


@needs_pg_dump
def test_restore_creates_a_new_database_and_never_overwrites(
    owner_api: Api, backups: Path, frozen: Any, tmp_path: Path
) -> None:
    key = _upload(owner_api)
    backup.run("cli")
    target = tmp_path / "restored-storage"
    current = make_url(backup.get_settings().database_url).database
    try:
        result = backup.restore("latest", RESTORED_DB, target)
        assert result["tables_differing"] == [] and result["files"] == result["files_expected"] == 1
        assert (target / key).read_bytes() == (backup.get_settings().storage_dir / key).read_bytes()
        assert "***" in result["database_url"] or make_url(result["database_url"]).password is None
        engine = create_engine(make_url(backup.get_settings().database_url).set(database=RESTORED_DB))
        with engine.connect() as conn:
            assert conn.execute(text("SELECT filename FROM sources")).scalar_one() == "notes.md"
        engine.dispose()

        for database, storage in (
            (RESTORED_DB, None),  # exists already
            (current, None),  # the database in use
            ("other_restore", target),  # folder not empty
            ("other_restore", backup.get_settings().storage_dir),  # the storage in use
        ):
            with pytest.raises(backup.BackupError) as exc:
                backup.restore("latest", database, storage)
            assert exc.value.code == "would_overwrite"
        with pytest.raises(backup.BackupError) as exc:
            backup.restore("latest", "Robert'); DROP", None)
        assert exc.value.code == "invalid_name"
        with pytest.raises(backup.BackupError) as exc:
            backup.restore("20200101-000000", "other_restore", None)
        assert exc.value.code == "no_snapshot"
        assert "other_restore" not in _databases()
    finally:
        _drop(RESTORED_DB)
