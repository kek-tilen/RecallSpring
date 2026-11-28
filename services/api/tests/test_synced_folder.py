"""A synced folder (2026-11-28): iCloud Drive and any other sync app, through the folder its app keeps on this
computer. The cloud copy of backups and learners' own copies go into a folder the first account chose; RecallSpring
makes only its last folder, never the folder above it (a missing sync folder or drive is reported, not replaced on the
local disk), writes each file as a hidden .part file first, gives every learner a subfolder of their own, follows
renamed and deleted folders, and Disconnect deletes only what RecallSpring made. No token is kept."""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from recallspring_api import backup, cloud, cloud_folder
from recallspring_api.db import new_session
from recallspring_api.main import create_app
from recallspring_api.models import Course, DriveItem
from recallspring_api.services import my_drive

from .conftest import Api, make_user
from .test_cloud_copy import _encryption_on, _sealed, _snapshot
from .test_my_drive import _upload


@pytest.fixture
def synced(settings: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A home folder with an iCloud Drive folder in it (as iCloud for Windows makes it)."""
    home = tmp_path / "home"
    icloud = home / "iCloudDrive"
    icloud.mkdir(parents=True)
    (icloud / "Holiday photos.txt").write_bytes(b"the learner's own file")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(settings, "backup_enabled", True)
    monkeypatch.setattr(settings, "backup_dir", tmp_path / "backups")
    monkeypatch.setattr(settings, "backup_settings_file", tmp_path / "backup-settings.json")
    monkeypatch.setattr(settings, "backup_settings_from_web", True)
    monkeypatch.setattr(settings, "run_dir", tmp_path / "run")
    monkeypatch.setattr(settings, "secrets_dir", tmp_path / "secrets")
    monkeypatch.setattr(settings, "cloud_google_client_id", None)
    monkeypatch.setattr(settings, "cloud_dropbox_app_key", None)
    monkeypatch.setattr(settings, "cloud_onedrive_client_id", None)
    monkeypatch.setattr(settings, "cloud_folder_dir", None)
    monkeypatch.setattr(settings, "drive_folder_dir", None)
    monkeypatch.setattr(cloud, "_spawn", lambda f: f())  # copies run inline in tests
    yield icloud


def _files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


# ---------------------------------------------------------------- checking a folder


def test_checking_a_folder_before_it_is_used(synced: Path, tmp_path: Path) -> None:
    assert cloud_folder.suggestions() == [{"app": "iCloud Drive", "path": str(synced)}]
    found = cloud_folder.check(str(synced / "RecallSpring backups"), "copy")
    assert found["ok"] and found["sync"] == "iCloud Drive" and not found["exists"]
    assert found["display"] == "iCloud Drive › RecallSpring backups"
    texts = {c["id"]: (c["level"], c["text"]) for c in found["checks"]}
    assert texts["write"][0] == "ok" and texts["write"][1].startswith("RecallSpring can make this folder")
    assert texts["upload"] == (
        "warn",
        "RecallSpring sees what it put in the folder, not when iCloud Drive has uploaded it.",
    )
    assert not (synced / "RecallSpring backups").exists()  # nothing is made by a check

    def refusal(raw: str, kind: str = "copy") -> str:
        r = cloud_folder.check(raw, kind)
        assert not r["ok"]
        return next(c["text"] for c in r["checks"] if c["level"] == "bad")

    assert refusal("relative/folder").startswith("Use the full path")
    assert "is not there" in refusal(str(tmp_path / "gone" / "RecallSpring"))  # never made on the local disk
    assert refusal(str(synced / "Holiday photos.txt")) == "That is a file, not a folder."
    assert "backup folder" in refusal(str(backup.backup_root() / "copy"))
    plain = cloud_folder.check(str(tmp_path / "nas"), "drive")
    assert plain["ok"] and plain["sync"] is None
    levels = {c["id"]: c["level"] for c in plain["checks"]}
    assert levels["sync"] == "warn" and levels["learners"] == "warn"


# ---------------------------------------------------------------- cloud copy of backups


def test_backups_go_to_a_synced_folder(owner_api: Api, synced: Path) -> None:
    view = owner_api.get("/settings/backup").json()["cloud"]
    assert view["available"]["folder"] is True
    assert view["folder"]["suggestions"] == [{"app": "iCloud Drive", "path": str(synced)}]
    target = str(synced / "RecallSpring backups")
    r = owner_api.post("/settings/backup/cloud/folder/connect", {"path": target})
    assert r.status_code == 409 and r.json()["code"] == "cloud_needs_encryption"
    _encryption_on()
    _snapshot("20261120-030000", [_sealed("a"), _sealed("b")])
    _snapshot("20261119-030000", [], encrypted=False)  # never leaves the computer
    assert owner_api.post("/settings/backup/cloud/folder/check", {"path": target}).json()["ok"] is True

    r = owner_api.post("/settings/backup/cloud/folder/connect", {"path": target})
    assert r.status_code == 200, r.text
    c = r.json()["cloud"]
    assert c["provider"] == "folder" and c["state"] == "ok" and c["backups"] == 1
    assert c["folder"] == {
        "path": target,
        "where": "iCloud Drive › RecallSpring backups",
        "sync": "iCloud Drive",
        "from_server": False,
    }
    assert c["free_bytes"] and c["free_bytes"] > 0
    copied = _files(synced / "RecallSpring backups")
    assert {f"sealed/{_sealed('a')}", f"sealed/{_sealed('b')}", "snapshots/20261120-030000/manifest.json"} <= copied
    assert not any("20261119" in f or ".part" in f for f in copied)
    assert owner_api.post("/settings/backup/cloud/folder/connect", {"path": target}).json()["code"] == "cloud_connected"
    history = [h for h in owner_api.get("/history").json() if h["type"] == "backup.cloud_connected"]
    assert history[0]["detail"] == "Synced folder (iCloud Drive)"
    assert not cloud._token_path("folder").exists()  # no sign-in, nothing kept in secrets_dir

    # The local folder removed a backup: the synced folder follows.
    for f in (backup.backup_root() / "snapshots" / "20261120-030000").iterdir():
        f.unlink()
    (backup.backup_root() / "snapshots" / "20261120-030000").rmdir()
    _snapshot("20261121-030000", [_sealed("a")])
    assert cloud.due() and cloud.copy_if_due()
    copied = _files(synced / "RecallSpring backups")
    assert "snapshots/20261121-030000/manifest.json" in copied and not any("20261120" in f for f in copied)
    assert f"sealed/{_sealed('b')}" not in copied

    # Disconnect › Delete them too: only what RecallSpring made.
    r = owner_api.post("/settings/backup/cloud/disconnect", {"delete_files": True})
    assert r.status_code == 200 and r.json()["cloud"]["state"] == "off"
    assert _files(synced) == {"Holiday photos.txt"}


def test_a_missing_sync_folder_is_reported_not_made_again(owner_api: Api, synced: Path, tmp_path: Path) -> None:
    _encryption_on()
    _snapshot("20261120-030000", [])
    target = synced / "RecallSpring backups"
    assert owner_api.post("/settings/backup/cloud/folder/connect", {"path": str(target)}).status_code == 200
    synced.rename(tmp_path / "signed-out")  # the sync app signed out and took its folder away
    _snapshot("20261121-030000", [])
    assert cloud.copy_if_due()
    c = owner_api.get("/settings/backup").json()["cloud"]
    assert c["state"] == "failing" and c["error"]["code"] == "folder_missing"
    assert "is not there" in c["error"]["message"] and not synced.exists()  # not made on the local disk
    item = cloud.attention_item()  # at once, not after a day
    assert item is not None and item["title"] == "Cloud copy is waiting for its folder"

    (tmp_path / "signed-out").rename(synced)
    cloud._update_status(next_try_at=None)
    assert cloud.copy_if_due() and owner_api.get("/settings/backup").json()["cloud"]["state"] == "ok"
    assert "snapshots/20261121-030000/manifest.json" in _files(target)


def test_the_server_settings_can_give_the_folder(
    owner_api: Api, synced: Path, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _encryption_on()
    monkeypatch.setattr(settings, "backup_settings_from_web", False)
    view = owner_api.get("/settings/backup").json()["cloud"]
    assert view["available"]["folder"] is False and view["folder"] is None and view["state"] == "off"
    monkeypatch.setattr(settings, "cloud_folder_dir", synced / "Server copy")
    view = owner_api.get("/settings/backup").json()["cloud"]  # the server settings turn it on; nothing to connect
    assert view["provider"] == "folder" and view["folder"]["path"] == str(synced / "Server copy")
    assert view["folder"]["from_server"] is True and view["folder"]["sync"] == "iCloud Drive"
    r = owner_api.post("/settings/backup/cloud/folder/connect", {"path": str(synced / "Somewhere else")})
    assert r.status_code == 403 and r.json()["code"] == "backup_folder_locked"
    _snapshot("20261120-030000", [])
    assert cloud.copy_if_due() and owner_api.get("/settings/backup").json()["cloud"]["state"] == "ok"
    assert (synced / "Server copy").is_dir() and not (synced / "Somewhere else").exists()
    r = owner_api.put("/drive/folder", {"path": str(synced / "Learners")})
    assert r.status_code == 409 and r.json()["code"] == "drive_folder_locked"


# ---------------------------------------------------------------- learners' own copies


def test_each_learner_gets_a_subfolder(owner_api: Api, synced: Path) -> None:
    off = owner_api.get("/drive").json()
    assert off["available"]["folder"] is False and off["synced_folder"]["can_choose"] is True
    assert off["synced_folder"]["suggestions"] == [{"app": "iCloud Drive", "path": str(synced)}]
    assert owner_api.post("/drive/folder/connect").json()["code"] == "drive_folder_missing"
    base = synced / "RecallSpring"
    assert owner_api.post("/drive/folder/check", {"path": str(base)}).json()["ok"] is True
    r = owner_api.put("/drive/folder", {"path": str(base)})
    assert r.status_code == 200 and r.json()["synced_folder"]["where"] == "iCloud Drive › RecallSpring"
    assert r.json()["synced_folder"]["mine"] == "iCloud Drive › RecallSpring › owner"

    cid = owner_api.post("/courses", {"title": "Biology"}).json()["id"]
    r = owner_api.post("/drive/folder/connect")
    assert r.status_code == 200 and r.json()["state"] == "connected", r.text
    v = r.json()["drive"]
    assert v["provider"] == "folder" and v["folder"] == "iCloud Drive › RecallSpring › owner"
    assert owner_api.post("/drive/onedrive/start").json()["code"] == "drive_connected"  # one at a time
    _upload(owner_api, cid, "Mitoza: povzetek.txt", b"Prophase.", "Week 1")
    _upload(owner_api, cid, "mitoza- POVZETEK.txt", b"Other case.", "Week 1")
    _upload(owner_api, cid, "big.txt", b"x" * 300_000, "Week 1")
    assert my_drive.sync_all() == 1
    mine = base / "owner"
    assert _files(mine) == {
        "Biology/Week 1/Mitoza- povzetek.txt",
        "Biology/Week 1/mitoza- POVZETEK (1).txt",
        "Biology/Week 1/big.txt",
    }
    assert (mine / "Biology/Week 1/big.txt").read_bytes() == b"x" * 300_000

    with new_session() as db:  # renamed in RecallSpring: renamed in the folder, and what is in it stays found
        course = db.get(Course, uuid.UUID(cid))
        assert course is not None
        course.title = "Cell Biology"
        db.commit()
    _upload(owner_api, cid, "b.txt", b"b", "Week 1")
    my_drive.sync_all()
    assert "Cell Biology/Week 1/b.txt" in _files(mine) and not (mine / "Biology").exists()
    assert not (mine / "Cell Biology (1)").exists()
    with new_session() as db:
        refs = set(db.scalars(select(DriveItem.drive_id)))
    assert all(not r.startswith("owner/Biology/") for r in refs)

    shutil.rmtree(mine / "Cell Biology" / "Week 1")  # deleted in the folder: made again, copied again
    _upload(owner_api, cid, "c.txt", b"c", "Week 1")
    my_drive.sync_all()
    my_drive.sync_all()
    assert {"Cell Biology/Week 1/c.txt", "Cell Biology/Week 1/b.txt"} <= _files(mine)

    # Another learner whose sign-in name differs only in letter case never shares the folder.
    make_user("Owner")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        assert other.login("Owner").status_code == 200
        seen = other.get("/drive").json()
        assert seen["available"]["folder"] is True and seen["synced_folder"]["can_choose"] is False
        assert seen["synced_folder"]["path"] is None  # the server's own path only for the first account
        assert other.put("/drive/folder", {"path": str(base)}).json()["code"] == "not_backup_owner"
        assert other.post("/drive/folder/check", {"path": str(base)}).status_code == 403
        r = other.post("/drive/folder/connect")
        assert r.status_code == 200 and r.json()["drive"]["folder"] == "iCloud Drive › RecallSpring › Owner (1)"
        assert (base / "Owner (1)").is_dir()
        assert other.post("/drive/disconnect", {"delete_files": True}).status_code == 200
        assert not (base / "Owner (1)").exists() and (base / "owner").is_dir()

    history = owner_api.get("/history").json()
    connected = next(h for h in history if h["type"] == "drive.connected")
    assert connected["detail"] == "Synced folder (iCloud Drive)"
    changed = next(h for h in history if h["type"] == "drive.folder_changed")
    assert changed["text"] == "Synced folder for learners changed" and changed["detail"] == f"none → {base}"
    assert json.dumps(v).count("refresh") == 0


def test_a_removed_folder_stops_copying_with_a_plain_message(owner_api: Api, synced: Path) -> None:
    assert owner_api.put("/drive/folder", {"path": str(synced / "RecallSpring")}).status_code == 200
    cid = owner_api.post("/courses", {"title": "Physics"}).json()["id"]
    assert owner_api.post("/drive/folder/connect").status_code == 200
    assert owner_api.put("/drive/folder", {"path": None}).status_code == 200  # no longer offered
    _upload(owner_api, cid, "a.txt", b"a")
    my_drive.sync_all()
    v = owner_api.get("/drive").json()
    assert v["state"] == "failing" and v["error"]["code"] == "folder_missing"
    assert v["error"]["message"].startswith("Whoever runs this RecallSpring no longer offers the synced folder")
    waiting = owner_api.get("/dashboard").json()["attention"]
    assert any(a["kind"] == "drive" and a["title"] == "Your synced folder copy is waiting" for a in waiting)
    assert (synced / "RecallSpring" / "Physics").exists() is False  # nothing was written meanwhile
    assert owner_api.post("/drive/disconnect", {"delete_files": False}).status_code == 200
    assert (synced / "RecallSpring" / "owner").is_dir()  # kept: the learner's copy
