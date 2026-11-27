"""Backups encrypted with a recovery key (docs/08 -> Backups, 2026-11-27): the server keeps only the public half,
nothing readable reaches the backup folder, and only the right key restores."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, make_url, select, text

from recallspring_api import backup
from recallspring_api.db import new_session
from recallspring_api.main import create_app
from recallspring_api.models import AuditEvent

from .conftest import Api, make_user
from .test_backup import _drop, _upload, needs_pg_dump

RESTORED_DB = "recallspring_test_restored_enc"


@pytest.fixture
def backups(settings: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "backups"
    monkeypatch.setattr(settings, "backup_enabled", True)
    monkeypatch.setattr(settings, "backup_dir", root)
    monkeypatch.setattr(settings, "backup_settings_file", tmp_path / "backup-settings.json")
    monkeypatch.setattr(settings, "backup_settings_from_web", True)
    monkeypatch.setattr(settings, "run_dir", tmp_path / "run")
    return root


def _turn_on(api: Api, remove_unencrypted: bool = False) -> dict[str, str]:
    r = api.post("/settings/backup/key")
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    key = r.json()
    assert key["identity"].startswith("AGE-SECRET-KEY-1") and key["recipient"].startswith("age1")
    on = api.put(
        "/settings/backup/encryption", {"recipient": key["recipient"], "remove_unencrypted": remove_unencrypted}
    )
    assert on.status_code == 200, on.text
    assert on.json()["encryption"] == {
        "on": True,
        "key_id": key["key_id"],
        "key_created_at": on.json()["encryption"]["key_created_at"],
    }
    return key


def test_the_server_keeps_only_the_public_half(owner_api: Api, backups: Path, settings: Any) -> None:
    key = _turn_on(owner_api)
    stored = settings.backup_settings_file.read_text(encoding="utf-8")
    assert key["recipient"] in stored and "AGE-SECRET-KEY" not in stored
    with new_session() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action.like("backup.%"))))
    assert [e.action for e in events] == ["backup.encryption_on"]
    assert "AGE-SECRET-KEY" not in json.dumps([e.details for e in events])
    row = next(h for h in owner_api.get("/history").json() if h["type"] == "backup.encryption_on")
    assert row["text"] == "Backup encryption turned on" and row["detail"] == f"key {key['key_id']}"

    bad = owner_api.put("/settings/backup/encryption", {"recipient": "age1notakey000000"})
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_key"

    second = _turn_on(owner_api)
    assert second["key_id"] != key["key_id"]
    assert owner_api.get("/settings/backup").json()["encryption"]["key_id"] == second["key_id"]


def test_only_the_first_account_manages_encryption(owner_api: Api, backups: Path) -> None:
    make_user("second")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        assert other.login("second").status_code == 200
        assert other.post("/settings/backup/key").status_code == 403
        r = other.put("/settings/backup/encryption", {"recipient": backup.new_key()["recipient"]})
        assert r.status_code == 403 and r.json()["code"] == "not_backup_owner"


@needs_pg_dump
def test_encrypted_backup_restores_only_with_its_key(
    owner_api: Api, backups: Path, frozen: Any, tmp_path: Path, settings: Any
) -> None:
    stored_key = _upload(owner_api)
    backup.run("cli")  # one plain backup first
    key = _turn_on(owner_api, remove_unencrypted=True)
    assert owner_api.get("/settings/backup").json()["unencrypted_snapshots"] == 1
    frozen.advance(hours=1)
    last = backup.run("cli")["last"]
    assert last["encrypted"] is True and last["check"] == "restored" and last["files"] == 1

    snap = backups / "snapshots" / last["snapshot"]
    assert sorted(p.name for p in snap.iterdir()) == ["db.dump.age", "manifest.json", "secret.json.age"]
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["encrypted"]["key_id"] == key["key_id"]
    assert "counts" not in manifest and manifest["files"]["keys"] == []
    assert stored_key not in json.dumps(manifest)  # which upload is which stays inside the encrypted part
    assert not (snap / "db.dump").exists()
    sealed = list((backups / "sealed").iterdir())
    assert len(sealed) == 1 and backup.SEALED_RE.match(sealed[0].name)
    original = (settings.storage_dir / stored_key).read_bytes()
    assert original[:20] not in sealed[0].read_bytes()
    # the plain backup was removed after this one, as asked, and its plain file with it
    assert [p.name for p in backup.snapshots()] == [last["snapshot"]]
    assert not [f for f in (backups / "files").rglob("*") if f.is_file()]
    assert not list((settings.run_dir / "backup-work").iterdir())  # the plain dump is gone
    view = owner_api.get("/settings/backup").json()
    assert view["unencrypted_snapshots"] == 0 and view["remove_unencrypted_pending"] is False

    with pytest.raises(backup.BackupError) as exc:
        backup.restore("latest", RESTORED_DB, None)
    assert exc.value.code == "key_needed"
    wrong = tmp_path / "wrong-key.txt"
    wrong.write_text(backup.new_key()["identity"], encoding="utf-8")
    with pytest.raises(backup.BackupError) as exc:
        backup.restore("latest", RESTORED_DB, None, key_file=wrong)
    assert exc.value.code == "wrong_key"

    right = tmp_path / "recovery-key.txt"
    right.write_text(f"# RecallSpring recovery key {key['key_id']}\n{key['identity']}\n", encoding="utf-8")
    target = tmp_path / "restored-storage"
    try:
        result = backup.restore("latest", RESTORED_DB, target, key_file=right)
        assert result["encrypted"] is True and result["tables_differing"] == []
        assert result["files"] == result["files_expected"] == 1
        assert (target / stored_key).read_bytes() == original
        engine = create_engine(make_url(backup.get_settings().database_url).set(database=RESTORED_DB))
        with engine.connect() as conn:
            assert conn.execute(text("SELECT filename FROM sources")).scalar_one() == "notes.md"
        engine.dispose()
    finally:
        _drop(RESTORED_DB)
    assert not list((settings.run_dir / "backup-work").iterdir())


@needs_pg_dump
def test_restore_reads_an_older_folder(owner_api: Api, backups: Path, frozen: Any, tmp_path: Path) -> None:
    _upload(owner_api)
    backup.run("cli")
    moved = tmp_path / "new-folder"
    assert owner_api.put("/settings/backup/folder", {"path": str(moved)}).status_code == 200
    with pytest.raises(backup.BackupError) as exc:
        backup.restore("latest", RESTORED_DB, None)
    assert exc.value.code == "no_snapshot"  # the new folder has none yet
    try:
        result = backup.restore("latest", RESTORED_DB, None, root=backups)
        assert result["tables_differing"] == [] and result["encrypted"] is False
    finally:
        _drop(RESTORED_DB)
