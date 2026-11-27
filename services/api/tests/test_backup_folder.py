"""Choosing where backups go from Settings (docs/08 -> Backups, 2026-11-27): the folder is checked before it is
saved, only the first account may change it, the server can lock it, and the change is audited."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from recallspring_api import backup
from recallspring_api.db import new_session
from recallspring_api.main import create_app
from recallspring_api.models import AuditEvent

from .conftest import Api, make_user


@pytest.fixture
def chosen(settings: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Its own settings file and server folder per test."""
    monkeypatch.setattr(settings, "backup_settings_file", tmp_path / "backup-settings.json")
    monkeypatch.setattr(settings, "backup_dir", tmp_path / "server-backups")
    monkeypatch.setattr(settings, "backup_settings_from_web", True)
    return tmp_path


def _levels(result: dict[str, Any]) -> dict[str, str]:
    return {c["id"]: c["level"] for c in result["checks"]}


def test_check_refuses_what_cannot_hold_backups(chosen: Path, settings: Any) -> None:
    assert not backup.check_folder("")["ok"]
    assert not backup.check_folder("relative/folder")["ok"]
    assert _levels(backup.check_folder(str(settings.storage_dir)))["place"] == "bad"
    assert _levels(backup.check_folder(str(settings.storage_dir / "inside")))["place"] == "bad"
    assert _levels(backup.check_folder(str(settings.storage_dir.parent)))["place"] == "bad"  # holds the uploads
    a_file = chosen / "a-file.txt"
    a_file.write_text("x", encoding="utf-8")
    assert _levels(backup.check_folder(str(a_file)))["place"] == "bad"
    drive_root = Path(chosen.anchor) if chosen.anchor else Path("/")
    assert not backup.check_folder(str(drive_root))["ok"]


def test_check_accepts_a_new_folder_and_creates_nothing(chosen: Path) -> None:
    target = chosen / "Dropbox" / "RecallSpring backups"
    result = backup.check_folder(f'  "{target}"  ')
    assert result["ok"], result
    assert result["path"] == str(target.resolve())
    assert result["sync"] == "Dropbox"
    assert _levels(result)["write"] in ("ok", "warn")
    assert not target.exists()
    assert not list(chosen.glob(".recallspring-write-check-*"))


def test_sync_folders_are_recognised_from_the_path() -> None:
    assert backup.sync_provider(Path("D:/Users/a/OneDrive - University/RS")) == "OneDrive"
    assert backup.sync_provider(Path("G:/My Drive/RS")) == "Google Drive"
    assert backup.sync_provider(Path("/Users/a/Library/Mobile Documents/com~apple~CloudDocs/RS")) == "iCloud Drive"
    assert backup.sync_provider(Path("C:/Users/a/iCloudDrive/RS")) == "iCloud Drive"
    assert backup.sync_provider(Path("E:/backups/RS")) is None


def test_owner_chooses_a_folder_and_it_is_audited(owner_api: Api, chosen: Path) -> None:
    view = owner_api.get("/settings/backup").json()
    assert view["can_change"] is True
    assert view["location_source"] == "server"
    target = chosen / "elsewhere" / "RecallSpring backups"
    checked = owner_api.post("/settings/backup/folder/check", {"path": str(target)})
    assert checked.status_code == 200 and checked.json()["ok"]
    assert not target.exists()

    saved = owner_api.put("/settings/backup/folder", {"path": str(target)})
    assert saved.status_code == 200, saved.text
    assert saved.json()["can_change"] is True  # every backup route returns the same view
    assert saved.json()["location"] == str(target.resolve())
    assert saved.json()["location_source"] == "settings"
    assert target.is_dir()
    assert backup.backup_root() == target.resolve()

    refused = owner_api.put("/settings/backup/folder", {"path": "not/absolute"})
    assert refused.status_code == 422 and refused.json()["code"] == "folder_refused"
    assert backup.backup_root() == target.resolve()

    back = owner_api.put("/settings/backup/folder", {"path": None})
    assert back.status_code == 200 and back.json()["location_source"] == "server"
    assert backup.backup_root() == chosen / "server-backups"

    with new_session() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "backup.folder_changed")))
    assert [e.details["to"] for e in events] == [str(target.resolve()), str(chosen / "server-backups")]
    shown = [r for r in owner_api.get("/history").json() if r["type"] == "backup.folder_changed"]
    assert shown[0]["text"] == "Backup folder changed"
    assert shown[0]["detail"] == f"{target.resolve()} → {chosen / 'server-backups'}"


def test_only_the_first_account_may_change_it(owner_api: Api, chosen: Path) -> None:
    make_user("second")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        assert other.login("second").status_code == 200
        assert other.get("/settings/backup").json()["can_change"] is False
        r = other.put("/settings/backup/folder", {"path": str(chosen / "x")})
        assert r.status_code == 403 and r.json()["code"] == "not_backup_owner"
        assert other.post("/settings/backup/folder/check", {"path": str(chosen / "x")}).status_code == 403


def test_the_server_can_keep_the_folder_to_itself(
    owner_api: Api, chosen: Path, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = chosen / "mine"
    assert owner_api.put("/settings/backup/folder", {"path": str(target)}).status_code == 200
    monkeypatch.setattr(settings, "backup_settings_from_web", False)
    assert backup.backup_root() == chosen / "server-backups"  # the saved choice is ignored
    view = owner_api.get("/settings/backup").json()
    assert view["can_change"] is False and view["folder_from_web"] is False
    r = owner_api.put("/settings/backup/folder", {"path": str(target)})
    assert r.status_code == 403 and r.json()["code"] == "backup_folder_locked"
