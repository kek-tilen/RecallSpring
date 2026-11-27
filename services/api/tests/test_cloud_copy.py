"""Cloud copy to Google Drive (docs/08 -> Backups -> Cloud copy, 2026-11-27), against a fake Google: code sign-in,
only encrypted backups leave, the cloud follows the local folder, resumable pieces, failures retried and shown in
Today after a day (at once when access is withdrawn), disconnect keeps or deletes the files. No secret in any view."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from recallspring_api import backup, cloud
from recallspring_api.db import new_session
from recallspring_api.main import create_app
from recallspring_api.models import AuditEvent

from .conftest import Api, FrozenClock, make_user

REFRESH = "1//fake-refresh-token-never-shown"
DEVICE = "fake-device-code-never-shown"


class FakeGoogle:
    """Just enough of Google's OAuth device flow and Drive v3 for cloud.py."""

    def __init__(self) -> None:
        self.files: dict[str, dict[str, Any]] = {}  # id -> {name, parent, folder, data}
        self.uploads: dict[str, dict[str, Any]] = {}
        self.approved = False
        self.revoked = False
        self.revoke_calls = 0
        self.limit: int | None = 10 * 1024**3
        self.drop_next_put = False
        self.puts = 0
        self.n = 0

    def _id(self) -> str:
        self.n += 1
        return f"f{self.n}"

    def tree(self, parent: str | None = None, prefix: str = "") -> set[str]:
        out: set[str] = set()
        for fid, f in self.files.items():
            if f["parent"] == parent:
                path = f"{prefix}{f['name']}"
                out |= {path + "/"} | self.tree(fid, path + "/") if f["folder"] else {path}
        return out

    def _delete(self, fid: str) -> None:
        for child in [k for k, v in self.files.items() if v["parent"] == fid]:
            self._delete(child)
        self.files.pop(fid, None)

    def handler(self, request: httpx.Request) -> httpx.Response:
        url, method = request.url, request.method
        form = (
            parse_qs(request.content.decode())
            if request.headers.get("content-type", "").startswith("application/x-www")
            else {}
        )
        if url.path == "/device/code":
            assert form["scope"] == [cloud.SCOPE]
            return httpx.Response(
                200,
                json={
                    "device_code": DEVICE,
                    "user_code": "WDJB-MJHT",
                    "verification_url": "https://www.google.com/device",
                    "expires_in": 1800,
                    "interval": 5,
                },
            )
        if url.path == "/token":
            grant = form["grant_type"][0]
            assert form["client_secret"] == ["test-secret"]
            if grant.endswith("device_code"):
                if not self.approved:
                    return httpx.Response(428, json={"error": "authorization_pending"})
                return httpx.Response(
                    200, json={"access_token": "at", "refresh_token": REFRESH, "expires_in": 3599, "scope": cloud.SCOPE}
                )
            if self.revoked:
                return httpx.Response(400, json={"error": "invalid_grant"})
            assert form["refresh_token"] == [REFRESH]
            return httpx.Response(200, json={"access_token": "at", "expires_in": 3599})
        if url.path == "/revoke":
            self.revoke_calls += 1
            return httpx.Response(200)
        assert request.headers.get("authorization") == "Bearer at"
        if url.path == "/drive/v3/about":
            used = sum(len(f.get("data", b"")) for f in self.files.values())
            quota = {"usage": str(used)} | ({"limit": str(self.limit)} if self.limit is not None else {})
            return httpx.Response(200, json={"storageQuota": quota})
        if url.path == "/drive/v3/files" and method == "GET":
            q = url.params["q"]
            parent = m.group(1) if (m := re.search(r"'([^']+)' in parents", q)) else None
            parent = None if parent == "root" else parent
            if parent and parent not in self.files:
                return httpx.Response(404, json={"error": {"message": "File not found"}})
            name = m.group(1) if (m := re.search(r"name='([^']+)'", q)) else None
            hits = [
                {
                    "id": fid,
                    "name": f["name"],
                    "mimeType": cloud.FOLDER_MIME if f["folder"] else "application/octet-stream",
                    **({} if f["folder"] else {"size": str(len(f["data"]))}),
                }
                for fid, f in self.files.items()
                if f["parent"] == parent and (name is None or f["name"] == name)
            ]
            return httpx.Response(200, json={"files": hits})
        if url.path == "/drive/v3/files" and method == "POST":
            meta = json.loads(request.content)
            fid = self._id()
            self.files[fid] = {"name": meta["name"], "parent": (meta.get("parents") or [None])[0], "folder": True}
            return httpx.Response(200, json={"id": fid})
        if url.path.startswith("/drive/v3/files/") and method == "DELETE":
            self._delete(url.path.rsplit("/", 1)[1])
            return httpx.Response(204)
        if url.path == "/upload/drive/v3/files" and method == "POST":
            meta = json.loads(request.content)
            uid = self._id()
            self.uploads[uid] = {"meta": meta, "size": int(request.headers["x-upload-content-length"]), "data": b""}
            return httpx.Response(
                200, headers={"Location": f"https://www.googleapis.com/upload/drive/v3/files?upload_id={uid}"}
            )
        if url.path == "/upload/drive/v3/files" and method == "PUT":
            up = self.uploads[url.params["upload_id"]]
            rng = request.headers["content-range"]
            if not rng.startswith("bytes */"):
                self.puts += 1
                if self.drop_next_put and self.puts > 1:
                    self.drop_next_put = False
                    up["data"] += request.content[: len(request.content) // 2]  # half arrived, then the line dropped
                    raise httpx.ConnectError("dropped")
                start = int(rng.split(" ")[1].split("-")[0])
                up["data"] = up["data"][:start] + request.content
            if len(up["data"]) < up["size"]:
                headers = {"Range": f"bytes=0-{len(up['data']) - 1}"} if up["data"] else {}
                return httpx.Response(308, headers=headers)
            fid = self._id()
            self.files[fid] = {
                "name": up["meta"]["name"],
                "parent": up["meta"]["parents"][0],
                "folder": False,
                "data": up["data"],
            }
            return httpx.Response(200, json={"id": fid, "size": str(len(up["data"]))})
        raise AssertionError(f"unexpected {method} {url}")


@pytest.fixture
def google(settings: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGoogle]:
    fake = FakeGoogle()
    monkeypatch.setattr(settings, "backup_enabled", True)
    monkeypatch.setattr(settings, "backup_dir", tmp_path / "backups")
    monkeypatch.setattr(settings, "backup_settings_file", tmp_path / "backup-settings.json")
    monkeypatch.setattr(settings, "backup_settings_from_web", True)
    monkeypatch.setattr(settings, "run_dir", tmp_path / "run")
    monkeypatch.setattr(settings, "secrets_dir", tmp_path / "secrets")
    monkeypatch.setattr(settings, "cloud_google_client_id", "test-client.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "cloud_google_client_secret", SecretStr("test-secret"))
    monkeypatch.setattr(cloud, "_transport", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(cloud, "_spawn", lambda f: f())  # copies run inline in tests
    yield fake


def _encryption_on() -> None:
    backup._write_json(backup.get_settings().backup_settings_file, {"recipient": backup.new_key()["recipient"]})


def _snapshot(name: str, sealed: list[str], *, encrypted: bool = True, size: int = 300) -> None:
    root = backup.backup_root()
    folder = root / "snapshots" / name
    folder.mkdir(parents=True)
    files = {"keys": [], "sealed": sealed} if encrypted else {"keys": []}
    (folder / "manifest.json").write_text(json.dumps({"encrypted": encrypted, "files": files}), encoding="utf-8")
    if encrypted:
        (folder / backup.DUMP_SEALED).write_bytes(b"d" * size)
        (folder / backup.SECRET_MANIFEST).write_bytes(b"s" * 40)
        for s in sealed:
            (root / "sealed").mkdir(exist_ok=True)
            (root / "sealed" / s).write_bytes(s.encode() * 3)
    else:
        (folder / "db.dump").write_bytes(b"plain")


def _sealed(c: str) -> str:
    return c * 64 + ".age"


def _connect(api: Api, fake: FakeGoogle, frozen: FrozenClock) -> dict[str, Any]:
    fake.approved = False
    r = api.post("/settings/backup/cloud/google/start")
    assert r.status_code == 200, r.text
    assert r.json()["user_code"] == "WDJB-MJHT" and DEVICE not in r.text
    assert api.post("/settings/backup/cloud/google/poll").json()["state"] == "pending"
    fake.approved = True
    assert api.post("/settings/backup/cloud/google/poll").json()["state"] == "pending"  # waits `interval` seconds
    frozen.advance(seconds=6)
    r = api.post("/settings/backup/cloud/google/poll")
    assert r.json()["state"] == "connected", r.text
    return r.json()["backup"]


def _actions() -> list[str]:
    with new_session() as db:
        return [e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.action.like("backup.cloud%")))]


def test_needs_an_app_id_and_encryption(
    owner_api: Api, google: FakeGoogle, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = owner_api.get("/settings/backup").json()["cloud"]
    assert view["available"] == {"google": True} and view["state"] == "off" and view["provider"] is None
    r = owner_api.post("/settings/backup/cloud/google/start")
    assert r.status_code == 409 and r.json()["code"] == "cloud_needs_encryption"
    _encryption_on()
    monkeypatch.setattr(settings, "cloud_google_client_id", None)
    assert owner_api.get("/settings/backup").json()["cloud"]["available"] == {"google": False}
    r = owner_api.post("/settings/backup/cloud/google/start")
    assert r.status_code == 409 and r.json()["code"] == "cloud_not_configured"
    assert "RS_CLOUD_GOOGLE_CLIENT_ID" in r.json()["message"]


def test_connect_copies_only_encrypted_backups_and_follows_the_folder(
    owner_api: Api, google: FakeGoogle, frozen: FrozenClock, settings: Any
) -> None:
    _encryption_on()
    _snapshot("20261118-030000", [], encrypted=False)
    _snapshot("20261119-030000", [_sealed("a"), _sealed("b")])
    _snapshot("20261120-030000", [_sealed("b"), _sealed("c")])
    view = _connect(owner_api, google, frozen)
    root = "RecallSpring backups/"
    assert google.tree() == {
        root,
        root + "snapshots/",
        root + "sealed/",
        *(root + f"sealed/{_sealed(c)}" for c in "abc"),
        *(root + f"snapshots/{n}/" for n in ("20261119-030000", "20261120-030000")),
        *(root + f"snapshots/{n}/{f}" for n in ("20261119-030000", "20261120-030000") for f in cloud.SNAPSHOT_FILES),
    }  # the unencrypted backup never left
    c = owner_api.get("/settings/backup").json()["cloud"]
    assert c["provider"] == "google" and c["state"] == "ok" and c["backups"] == 2 and c["bytes"] > 0
    assert c["free_bytes"] is not None and c["pending"] is None
    for text in (json.dumps(view), json.dumps(c)):
        assert REFRESH not in text and DEVICE not in text
    for kept in (settings.backup_settings_file, cloud._status_path()):
        assert REFRESH.encode() not in kept.read_bytes()
    if os.name == "nt":  # DPAPI; elsewhere the file is readable by its owner only
        assert REFRESH.encode() not in (settings.secrets_dir / "cloud-google.bin").read_bytes()
    assert not cloud.due()
    assert _actions() == ["backup.cloud_connected"]
    history = [h for h in owner_api.get("/history").json() if h["type"] == "backup.cloud_connected"]
    assert history[0]["text"] == "Cloud copy connected" and history[0]["detail"] == "Google Drive"

    # The local folder dropped the oldest backup (and file a): the cloud does the same; a new backup is copied.
    import shutil

    shutil.rmtree(backup.backup_root() / "snapshots" / "20261119-030000")
    (backup.backup_root() / "sealed" / _sealed("a")).unlink()
    _snapshot("20261121-030000", [_sealed("c")])
    assert cloud.due() and cloud.copy_if_due()
    names = google.tree()
    assert root + "snapshots/20261119-030000/" not in names and root + f"sealed/{_sealed('a')}" not in names
    assert root + "snapshots/20261121-030000/manifest.json" in names
    assert owner_api.get("/settings/backup").json()["cloud"]["backups"] == 2


def test_a_dropped_piece_continues_where_it_stopped(
    owner_api: Api, google: FakeGoogle, frozen: FrozenClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cloud, "CHUNK", 256 * 1024)
    _encryption_on()
    _snapshot("20261119-030000", [], size=700 * 1024)
    google.drop_next_put = True
    _connect(owner_api, google, frozen)
    dump = next(f for f in google.files.values() if f["name"] == backup.DUMP_SEALED)
    assert dump["data"] == b"d" * 700 * 1024
    assert owner_api.get("/settings/backup").json()["cloud"]["state"] == "ok"


def test_no_room_is_retried_and_shown_after_a_day(owner_api: Api, google: FakeGoogle, frozen: FrozenClock) -> None:
    _encryption_on()
    _snapshot("20261119-030000", [_sealed("a")])
    google.limit = 100
    _connect(owner_api, google, frozen)
    c = owner_api.get("/settings/backup").json()["cloud"]
    assert c["state"] == "failing" and c["error"]["code"] == "no_room" and "needs" in c["error"]["message"]
    assert not cloud.due()  # waits until tomorrow
    assert cloud.attention_item() is None  # one failed night is not shown in Today
    frozen.advance(hours=21)
    assert cloud.due() and cloud.copy_if_due()  # fails again: recorded once, not per retry
    assert _actions().count("backup.cloud_failed") == 1
    frozen.advance(hours=4)
    item = cloud.attention_item()
    assert item is not None and item["title"] == "Cloud copy is failing" and "needs" in item["text"]
    google.limit = None
    frozen.advance(hours=21)
    assert cloud.copy_if_due()
    assert owner_api.get("/settings/backup").json()["cloud"]["state"] == "ok" and cloud.attention_item() is None


def test_withdrawn_access_stops_and_says_so_at_once(owner_api: Api, google: FakeGoogle, frozen: FrozenClock) -> None:
    _encryption_on()
    _snapshot("20261119-030000", [])
    _connect(owner_api, google, frozen)
    google.revoked = True
    _snapshot("20261120-030000", [])
    assert cloud.copy_if_due()
    c = owner_api.get("/settings/backup").json()["cloud"]
    assert c["state"] == "revoked" and c["next_try_at"] is None
    assert not cloud.due()
    item = cloud.attention_item()
    assert item is not None and item["title"] == "Cloud copy stopped"


def test_disconnect_keeps_or_deletes_the_files(
    owner_api: Api, google: FakeGoogle, frozen: FrozenClock, settings: Any
) -> None:
    _encryption_on()
    _snapshot("20261119-030000", [])
    _connect(owner_api, google, frozen)
    r = owner_api.post("/settings/backup/cloud/disconnect", {"delete_files": False})
    assert r.status_code == 200 and r.json()["cloud"]["state"] == "off"
    assert google.tree() and google.revoke_calls == 1
    assert not (settings.secrets_dir / "cloud-google.bin").exists()
    _connect(owner_api, google, frozen)  # finds the same folder again
    assert len([f for f in google.files.values() if f["name"] == cloud.ROOT_NAME]) == 1
    r = owner_api.post("/settings/backup/cloud/disconnect", {"delete_files": True})
    assert r.status_code == 200 and google.tree() == set()
    assert _actions() == [
        "backup.cloud_connected",
        "backup.cloud_disconnected",
        "backup.cloud_connected",
        "backup.cloud_files_deleted",
        "backup.cloud_disconnected",
    ]


def test_only_the_first_account_connects(owner_api: Api, google: FakeGoogle) -> None:
    _encryption_on()
    make_user("second")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        assert other.login("second").status_code == 200
        r = other.post("/settings/backup/cloud/google/start")
        assert r.status_code == 403 and r.json()["code"] == "not_backup_owner"
        assert other.post("/settings/backup/cloud/disconnect", {"delete_files": True}).status_code == 403


def test_a_folder_deleted_in_drive_is_made_again(owner_api: Api, google: FakeGoogle, frozen: FrozenClock) -> None:
    _encryption_on()
    _snapshot("20261119-030000", [])
    _connect(owner_api, google, frozen)
    root = next(k for k, f in google.files.items() if f["name"] == cloud.ROOT_NAME)
    google._delete(root)
    frozen.advance(minutes=1)
    owner_api.post("/settings/backup/cloud/copy")
    assert "RecallSpring backups/snapshots/20261119-030000/manifest.json" in google.tree()
