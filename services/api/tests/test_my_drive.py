"""Your Google Drive (BYOS step 2, 2026-11-27), against a fake Google: each learner signs in with their own account,
new material is copied by course as readable files, earlier material only when asked, renamed folders follow,
deleted folders are made again, failures wait and withdrawn access shows in Today, Disconnect keeps or deletes the
files, and exports can go there. No secret in any view or History."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from recallspring_api import cloud
from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent, Course, DriveItem, Export
from recallspring_api.services import exports, my_drive

from .conftest import Api, FrozenClock, run_pending
from .test_cloud_copy import DEVICE, REFRESH, FakeGoogle


class FakeDrive(FakeGoogle):
    """FakeGoogle plus reading and renaming one file (files/{id})."""

    def __init__(self) -> None:
        super().__init__()
        self.trashed: set[str] = set()
        self.renames = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        url, method = request.url, request.method
        if url.path.startswith("/drive/v3/files/") and method in ("GET", "PATCH"):
            assert request.headers.get("authorization") == "Bearer at"
            fid = url.path.rsplit("/", 1)[1]
            f = self.files.get(fid)
            if f is None:
                return httpx.Response(404, json={"error": {"message": "File not found"}})
            if method == "PATCH":
                f["name"] = json.loads(request.content)["name"]
                self.renames += 1
                return httpx.Response(200, json={"id": fid})
            return httpx.Response(200, json={"id": fid, "name": f["name"], "trashed": fid in self.trashed})
        return super().handler(request)

    def find(self, path: str) -> str:
        parent: str | None = None
        for part in path.split("/"):
            parent = next(k for k, v in self.files.items() if v["parent"] == parent and v["name"] == part)
        assert parent is not None
        return parent


@pytest.fixture
def drive(settings: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeDrive]:
    fake = FakeDrive()
    monkeypatch.setattr(settings, "run_dir", tmp_path / "run")
    monkeypatch.setattr(settings, "secrets_dir", tmp_path / "secrets")
    monkeypatch.setattr(settings, "cloud_google_client_id", "test-client.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "cloud_google_client_secret", SecretStr("test-secret"))
    monkeypatch.setattr(cloud, "_transport", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(cloud, "_spawn", lambda f: f())  # copies run inline in tests
    yield fake


def _connect(api: Api, fake: FakeDrive) -> dict[str, Any]:
    start = api.post("/drive/start")
    assert start.status_code == 200, start.text
    assert start.json()["user_code"] == "WDJB-MJHT" and DEVICE not in start.text
    fake.approved = True
    polled = api.post("/drive/poll")
    assert polled.status_code == 200 and polled.json()["state"] == "connected", polled.text
    return polled.json()["drive"]


def _upload(api: Api, course_id: str, name: str, data: bytes, folder_path: str | None = None) -> None:
    form = {"course_id": course_id, **({"folder_path": folder_path} if folder_path else {})}
    r = api.client.post("/api/v1/sources", data=form, files={"file": (name, data)}, headers=api.headers())
    assert r.status_code in (200, 201), r.text


def _actions() -> list[str]:
    with new_session() as db:
        return list(db.scalars(select(AuditEvent.action).order_by(AuditEvent.occurred_at)))


def _no_secrets(*texts: str) -> None:
    with new_session() as db:
        details = json.dumps([e.details for e in db.scalars(select(AuditEvent))], default=str)
    for t in (*texts, details):
        assert REFRESH not in t and DEVICE not in t and "test-secret" not in t


def test_new_material_is_copied_by_course_and_earlier_only_when_asked(owner_api: Api, drive: FakeDrive) -> None:
    cid = owner_api.post("/courses", {"title": "Biology"}).json()["id"]
    _upload(owner_api, cid, "Before.txt", b"old")
    off = owner_api.get("/drive").json()
    assert off["state"] == "off" and off["available"] is True and off["pending"] is None

    v = _connect(owner_api, drive)
    assert v["state"] == "ok" and v["folder"] == "My Drive › RecallSpring"
    assert v["mirror"] is True and v["exports"] is False
    assert v["not_yet"] == {"files": 1, "bytes": 3}
    assert drive.tree() == {"RecallSpring/"}  # nothing from before is copied on its own

    _upload(owner_api, cid, "Lab sheet.txt", b"Measure the CO2 output.", "Week 1/Labs")
    assert my_drive.sync_all() == 1
    assert drive.tree() == {
        "RecallSpring/",
        "RecallSpring/Biology/",
        "RecallSpring/Biology/Week 1/",
        "RecallSpring/Biology/Week 1/Labs/",
        "RecallSpring/Biology/Week 1/Labs/Lab sheet.txt",
    }
    lab = drive.files[drive.find("RecallSpring/Biology/Week 1/Labs/Lab sheet.txt")]
    assert lab["data"] == b"Measure the CO2 output."
    assert my_drive.sync_all() == 0  # nothing waiting
    v = owner_api.get("/drive").json()
    assert (v["files"], v["bytes"], v["last_success_at"] is not None) == (1, 23, True)

    r = owner_api.post("/drive/copy-existing")
    assert r.status_code == 202, r.text
    assert "RecallSpring/Biology/Before.txt" in drive.tree()
    after = owner_api.get("/drive")
    assert after.json()["not_yet"] == {"files": 0, "bytes": 0} and after.json()["files"] == 2

    assert {"drive.connected", "drive.copy_existing"} <= set(_actions())
    _no_secrets(json.dumps(off), after.text, owner_api.get("/history").text)


def test_renamed_folders_follow_and_deleted_ones_are_made_again(owner_api: Api, drive: FakeDrive) -> None:
    cid = owner_api.post("/courses", {"title": "Physics"}).json()["id"]
    _connect(owner_api, drive)
    _upload(owner_api, cid, "a.txt", b"a", "Week 1")
    my_drive.sync_all()
    folder_id = next(f["id"] for f in owner_api.get("/folders", course_id=cid).json() if f["name"] == "Week 1")
    assert owner_api.patch(f"/folders/{folder_id}", {"name": "Week one"}).status_code == 200
    _upload(owner_api, cid, "b.txt", b"b", "Week one")
    my_drive.sync_all()
    assert {"RecallSpring/Physics/Week one/a.txt", "RecallSpring/Physics/Week one/b.txt"} <= drive.tree()
    assert drive.renames == 1

    with new_session() as db:  # renamed in RecallSpring
        course = db.get(Course, uuid.UUID(cid))
        assert course is not None
        course.title = "Physics I"
        db.commit()
    drive._delete(drive.find("RecallSpring/Physics"))  # and the learner deleted the folder in Drive
    _upload(owner_api, cid, "c.txt", b"c")
    my_drive.sync_all()
    assert "RecallSpring/Physics I/c.txt" in drive.tree()
    my_drive.sync_all()  # what was in the deleted folder is copied again
    assert {"RecallSpring/Physics I/Week one/a.txt", "RecallSpring/Physics I/Week one/b.txt"} <= drive.tree()

    drive.trashed.add(drive.find("RecallSpring/Physics I/Week one"))  # in the bin counts as gone
    _upload(owner_api, cid, "d.txt", b"d", "Week one")
    my_drive.sync_all()
    my_drive.sync_all()
    copies = {name: sum(f["name"] == name for f in drive.files.values()) for name in ("a.txt", "d.txt")}
    assert copies == {"a.txt": 2, "d.txt": 1}  # the binned folder keeps its copy; a new folder holds all again
    with new_session() as db:
        n = db.scalar(select(func.count()).select_from(DriveItem).where(DriveItem.local_kind == "source"))
    assert n == 4


def test_failures_wait_and_withdrawn_access_shows_in_today(
    owner_api: Api, drive: FakeDrive, frozen: FrozenClock
) -> None:
    cid = owner_api.post("/courses", {"title": "Physics"}).json()["id"]
    _connect(owner_api, drive)
    drive.limit = 10
    _upload(owner_api, cid, "big.txt", b"x" * 100)
    assert my_drive.sync_all() == 0
    v = owner_api.get("/drive").json()
    assert v["state"] == "failing" and v["error"]["code"] == "no_room" and v["next_try_at"]
    assert not any(a["kind"] == "drive" for a in owner_api.get("/dashboard").json()["attention"])

    drive.limit = None
    frozen.advance(hours=1)
    assert my_drive.sync_all() == 0 and "RecallSpring/Physics/big.txt" not in drive.tree()  # waits until tomorrow
    frozen.advance(hours=20)
    assert my_drive.sync_all() == 1 and owner_api.get("/drive").json()["state"] == "ok"

    drive.revoked = True
    _upload(owner_api, cid, "next.txt", b"n")
    my_drive.sync_all()
    v = owner_api.get("/drive").json()
    assert v["state"] == "revoked" and "no longer allows" in v["error"]["message"]
    waiting = owner_api.get("/dashboard").json()["attention"]
    assert any(a["kind"] == "drive" and a["title"] == "Your Google Drive copy stopped" for a in waiting)
    assert _actions().count("drive.failed") == 2  # once per failing streak

    drive.revoked = False  # connect again: what was copied stays mapped, the rest follows
    _connect(owner_api, drive)
    assert owner_api.get("/drive").json()["state"] == "ok"
    assert "RecallSpring/Physics/next.txt" in drive.tree()
    assert sum(1 for f in drive.files.values() if f["parent"] is None) == 1  # the same folder again


def test_disconnect_keeps_or_deletes_the_files(owner_api: Api, drive: FakeDrive, tmp_path: Path) -> None:
    cid = owner_api.post("/courses", {"title": "Physics"}).json()["id"]
    _connect(owner_api, drive)
    assert owner_api.post("/drive/settings", {"mirror": False}).json()["mirror"] is False
    _upload(owner_api, cid, "a.txt", b"a")
    assert my_drive.sync_all() == 0 and drive.tree() == {"RecallSpring/"}
    owner_api.post("/drive/settings", {"mirror": True})  # turning it on copies what waits
    assert "RecallSpring/Physics/a.txt" in drive.tree()

    kept = owner_api.post("/drive/disconnect", {})
    assert kept.status_code == 200 and kept.json()["state"] == "off"
    assert "RecallSpring/Physics/a.txt" in drive.tree() and drive.revoke_calls == 1
    assert not list((tmp_path / "secrets").glob("drive-*"))
    with new_session() as db:
        assert db.scalar(select(func.count()).select_from(DriveItem)) == 0

    _connect(owner_api, drive)
    gone = owner_api.post("/drive/disconnect", {"delete_files": True})
    assert gone.status_code == 200 and drive.tree() == set()
    with new_session() as db:
        events = select(AuditEvent).where(AuditEvent.action == "drive.disconnected").order_by(AuditEvent.occurred_at)
        files = [e.details["files"] for e in db.scalars(events)]
    assert files == ["kept", "deleted"]
    assert owner_api.post("/drive/settings", {"mirror": True}).status_code == 409


def test_exports_go_to_drive_when_chosen(owner_api: Api, drive: FakeDrive) -> None:
    cid = owner_api.post("/courses", {"title": "Physics"}).json()["id"]
    note = {"course_id": cid, "client_note_id": str(uuid.uuid4()), "title": "Forces", "body": "F = ma"}
    assert owner_api.post("/notes", note).status_code == 201
    _connect(owner_api, drive)
    refused = owner_api.post("/exports", {"destination": "drive"})
    assert refused.status_code == 409 and refused.json()["code"] == "drive_not_connected"
    assert owner_api.get("/exports").json()["drive"] is False
    assert owner_api.post("/drive/settings", {"exports": True}).json()["exports"] is True
    assert owner_api.get("/exports").json()["drive"] is True

    assert owner_api.post("/exports", {"destination": "drive"}).status_code == 202
    run_pending()
    current = owner_api.get("/exports").json()["current"]
    assert current["state"] == "expired" and current["destination"] == "drive" and current["error"] is None
    sent = [p for p in drive.tree() if p.startswith("RecallSpring/Exports/RecallSpring export ")]
    assert len(sent) == 1 and sent[0].endswith(".zip")
    with new_session() as db:
        row = db.get(Export, uuid.UUID(current["id"]))
        assert row is not None and not exports.zip_path(row).exists()
    assert "export.sent_to_drive" in _actions()

    drive.revoked = True  # Drive fails: the ZIP stays here to download
    assert owner_api.post("/exports", {"destination": "drive"}).status_code == 202
    run_pending()
    current = owner_api.get("/exports").json()["current"]
    assert current["state"] == "ready" and current["error"] == "drive_revoked"
    waiting = owner_api.get("/dashboard").json()["attention"]
    assert any(a["title"] == "Your export could not go to Google Drive" for a in waiting)
    assert owner_api.client.get(f"/api/v1/exports/{current['id']}/download").status_code == 200
    assert owner_api.get("/drive").json()["state"] == "revoked"
