"""Dropbox (2026-11-28), against a fake Dropbox: the cloud copy of backups and a learner's own cloud folder go to the
app folder, the sign-in is a code Dropbox shows (PKCE: the verifier never leaves the server, no app secret), large
files go in pieces and continue after a drop, a full Dropbox and withdrawn access are said plainly, renamed and
deleted folders are followed, Disconnect deletes only what RecallSpring made, and one provider is used at a time.
No secret in any view, file or History."""

from __future__ import annotations

import base64
import hashlib
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import select

from recallspring_api import cloud, cloud_dropbox
from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent, Course
from recallspring_api.services import my_drive

from .conftest import Api, FrozenClock
from .test_cloud_copy import _encryption_on, _sealed, _snapshot
from .test_my_drive import _upload

KEY = "test-dropbox-app-key"
REFRESH = "dbx-fake-refresh-token-never-shown"
CODE = "dbx-good-code-0123456789"


def _err(*tags: str, **extra: Any) -> httpx.Response:
    """A 409 with nested .tag values, as Dropbox sends them."""
    inner: dict[str, Any] = {".tag": tags[-1], **extra}
    for tag in reversed(tags[:-1]):
        inner = {".tag": tag, tag: inner}
    return httpx.Response(409, json={"error_summary": "/".join(tags) + "/..", "error": inner})


class FakeDropbox:
    """Just enough of Dropbox's OAuth (PKCE) and files API for cloud_dropbox.py. Ids look like Dropbox's."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}  # id -> {name, parent ("" = app folder), folder, data}
        self.sessions: dict[str, bytearray] = {}
        self.challenge: str | None = None
        self.revoked = False
        self.revoke_calls = 0
        self.limit: int | None = None
        self.drop_next_append = False
        self.moves = 0
        self.n = 0

    # -- the tree

    def _id(self) -> str:
        self.n += 1
        return f"id:fake{self.n:04d}"

    def _child(self, parent: str, name: str) -> str | None:
        return next(
            (k for k, v in self.items.items() if v["parent"] == parent and v["name"].lower() == name.lower()), None
        )

    def resolve(self, path: str) -> str | None:
        if path == "":
            return ""
        if path.startswith("id:"):
            return path if path in self.items else None
        cur = ""
        for part in path.strip("/").split("/"):
            nxt = self._child(cur, part)
            if nxt is None:
                return None
            cur = nxt
        return cur

    def path(self, fid: str) -> str:
        parts = []
        while fid:
            parts.append(self.items[fid]["name"])
            fid = self.items[fid]["parent"]
        return "/" + "/".join(reversed(parts))

    def tree(self, parent: str = "", prefix: str = "") -> set[str]:
        out: set[str] = set()
        for fid, f in self.items.items():
            if f["parent"] == parent:
                p = f"{prefix}{f['name']}"
                out |= {p + "/"} | self.tree(fid, p + "/") if f["folder"] else {p}
        return out

    def find(self, path: str) -> str:
        found = self.resolve("/" + path)
        assert found, path
        return found

    def remove(self, fid: str) -> None:
        for child in [k for k, v in self.items.items() if v["parent"] == fid]:
            self.remove(child)
        self.items.pop(fid, None)

    def meta(self, fid: str) -> dict[str, Any]:
        f = self.items[fid]
        m = {
            ".tag": "folder" if f["folder"] else "file",
            "id": fid,
            "name": f["name"],
            "path_display": self.path(fid),
            "path_lower": self.path(fid).lower(),
        }
        return m if f["folder"] else m | {"size": len(f["data"])}

    def _free_name(self, parent: str, name: str) -> str:
        if self._child(parent, name) is None:
            return name
        stem, dot, ext = name.rpartition(".") if "." in name else (name, "", "")
        i = 1
        while self._child(parent, f"{stem} ({i}){dot}{ext}") is not None:
            i += 1
        return f"{stem} ({i}){dot}{ext}"

    def _place(self, path: str, autorename: bool) -> tuple[str, str] | httpx.Response:
        parent_path, _, name = path.rpartition("/")
        parent = self.resolve(parent_path)
        if parent is None:
            return _err("path", "not_found")
        if self._child(parent, name) is not None:
            if not autorename:
                return _err("path", "conflict", conflict={".tag": "folder"})
            name = self._free_name(parent, name)
        return parent, name

    def _write(self, args: dict[str, Any], data: bytes) -> httpx.Response:
        used = sum(len(v.get("data", b"")) for v in self.items.values())
        if self.limit is not None and used + len(data) > self.limit:
            return _err("path", "reason", "insufficient_space")
        placed = self._place(args["path"], bool(args.get("autorename")))
        if isinstance(placed, httpx.Response):
            return placed
        fid = self._id()
        self.items[fid] = {"name": placed[1], "parent": placed[0], "folder": False, "data": bytes(data)}
        return httpx.Response(200, json=self.meta(fid))

    # -- requests

    def handler(self, request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if path == "/oauth2/token":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            assert form["client_id"] == KEY and "client_secret" not in form  # PKCE: no app secret
            if form["grant_type"] == "authorization_code":
                digest = hashlib.sha256(form["code_verifier"].encode()).digest()
                assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == self.challenge
                if form["code"] != CODE:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(
                    200,
                    json={"access_token": "at", "refresh_token": REFRESH, "expires_in": 14400, "account_id": "dbid:x"},
                )
            if self.revoked:
                return httpx.Response(400, json={"error": "invalid_grant"})
            assert form["refresh_token"] == REFRESH
            return httpx.Response(200, json={"access_token": "at", "expires_in": 14400})
        assert request.headers.get("authorization") == "Bearer at"
        if path == "/2/auth/token/revoke":
            self.revoke_calls += 1
            return httpx.Response(200, json={})
        if host == "content.dropboxapi.com":
            raw = request.headers["dropbox-api-arg"]
            assert raw.isascii()  # non-ASCII names are \u-escaped
            return self._content(path, json.loads(raw), request.content)
        args = json.loads(request.content)
        if path == "/2/files/get_metadata":
            fid = self.resolve(args["path"])
            return httpx.Response(200, json=self.meta(fid)) if fid else _err("path", "not_found")
        if path == "/2/files/list_folder":
            fid = self.resolve(args["path"])
            if fid is None:
                return _err("path", "not_found")
            entries = [self.meta(k) for k, v in self.items.items() if v["parent"] == fid]
            return httpx.Response(200, json={"entries": entries, "cursor": "c", "has_more": False})
        if path == "/2/files/create_folder_v2":
            placed = self._place(args["path"], bool(args.get("autorename")))
            if isinstance(placed, httpx.Response):
                return placed
            fid = self._id()
            self.items[fid] = {"name": placed[1], "parent": placed[0], "folder": True}
            return httpx.Response(200, json={"metadata": self.meta(fid)})
        if path == "/2/files/delete_v2":
            fid = self.resolve(args["path"])
            if not fid:
                return _err("path_lookup", "not_found")
            m = self.meta(fid)
            self.remove(fid)
            return httpx.Response(200, json={"metadata": m})
        if path == "/2/files/move_v2":
            fid = self.resolve(args["from_path"])
            assert fid, args
            placed = self._place(args["to_path"], bool(args.get("autorename")))
            assert not isinstance(placed, httpx.Response)
            self.items[fid]["parent"], self.items[fid]["name"] = placed
            self.moves += 1
            return httpx.Response(200, json={"metadata": self.meta(fid)})
        raise AssertionError(f"unexpected {request.method} {request.url}")

    def _content(self, path: str, args: dict[str, Any], data: bytes) -> httpx.Response:
        if path == "/2/files/upload":
            return self._write(args, data)
        if path == "/2/files/upload_session/start":
            sid = f"s{len(self.sessions) + 1}"
            self.sessions[sid] = bytearray(data)
            return httpx.Response(200, json={"session_id": sid})
        cursor = args["cursor"]
        got = self.sessions[cursor["session_id"]]
        if cursor["offset"] != len(got):
            return _err("incorrect_offset", correct_offset=len(got))
        if path == "/2/files/upload_session/append_v2":
            if self.drop_next_append:
                self.drop_next_append = False
                got.extend(data[: len(data) // 2])  # half arrived, then the line dropped
                raise httpx.ConnectError("dropped")
            got.extend(data)
            return httpx.Response(200, json={})
        if path == "/2/files/upload_session/finish":
            got.extend(data)
            return self._write(args["commit"], bytes(got))
        raise AssertionError(f"unexpected content call {path}")


@pytest.fixture
def dbx(settings: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeDropbox]:
    fake = FakeDropbox()
    monkeypatch.setattr(settings, "backup_enabled", True)
    monkeypatch.setattr(settings, "backup_dir", tmp_path / "backups")
    monkeypatch.setattr(settings, "backup_settings_file", tmp_path / "backup-settings.json")
    monkeypatch.setattr(settings, "backup_settings_from_web", True)
    monkeypatch.setattr(settings, "run_dir", tmp_path / "run")
    monkeypatch.setattr(settings, "secrets_dir", tmp_path / "secrets")
    monkeypatch.setattr(settings, "cloud_google_client_id", None)
    monkeypatch.setattr(settings, "cloud_dropbox_app_key", KEY)
    monkeypatch.setattr(cloud, "_transport", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(cloud, "_spawn", lambda f: f())  # copies run inline in tests
    monkeypatch.setattr(cloud_dropbox, "CHUNK", 64 * 1024)  # small pieces in tests (4 MiB multiples in real use)
    yield fake


def _authorize(fake: FakeDropbox, start: httpx.Response) -> str:
    """Check the page RecallSpring opens, and remember its challenge as Dropbox would."""
    assert start.status_code == 200, start.text
    body = start.json()
    assert body["provider"] == "dropbox" and "verifier" not in start.text
    url = urlparse(body["authorize_url"])
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert url.netloc == "www.dropbox.com" and url.path == "/oauth2/authorize"
    assert q["client_id"] == KEY and q["response_type"] == "code" and q["code_challenge_method"] == "S256"
    assert q["token_access_type"] == "offline" and q["scope"] == "files.metadata.read files.content.write"
    assert "redirect_uri" not in q  # Dropbox shows the code instead
    fake.challenge = q["code_challenge"]
    return body["authorize_url"]


def _connect_backups(api: Api, fake: FakeDropbox) -> dict[str, Any]:
    _authorize(fake, api.post("/settings/backup/cloud/dropbox/start"))
    r = api.post("/settings/backup/cloud/dropbox/finish", {"code": f"  {CODE} "})
    assert r.status_code == 200 and r.json()["state"] == "connected", r.text
    return r.json()["backup"]


def _connect_folder(api: Api, fake: FakeDropbox) -> dict[str, Any]:
    _authorize(fake, api.post("/drive/dropbox/start"))
    r = api.post("/drive/dropbox/finish", {"code": CODE})
    assert r.status_code == 200 and r.json()["state"] == "connected", r.text
    return r.json()["drive"]


def _audit_text() -> str:
    with new_session() as db:
        return json.dumps([e.details for e in db.scalars(select(AuditEvent))], default=str)


def _no_secrets(*texts: str) -> None:
    for t in (*texts, _audit_text()):
        assert REFRESH not in t and CODE not in t


# ---------------------------------------------------------------- cloud copy of backups


def test_backups_go_to_the_app_folder_after_a_pasted_code(
    owner_api: Api, dbx: FakeDropbox, settings: Any, frozen: FrozenClock
) -> None:
    view = owner_api.get("/settings/backup").json()["cloud"]
    assert view["available"] == {"google": False, "dropbox": True}
    assert owner_api.post("/settings/backup/cloud/dropbox/start").json()["code"] == "cloud_needs_encryption"
    _encryption_on()
    _snapshot("20261120-030000", [_sealed("a")], size=200 * 1024)  # bigger than a piece: an upload session
    dbx.drop_next_append = True

    _authorize(dbx, owner_api.post("/settings/backup/cloud/dropbox/start"))
    pending = owner_api.get("/settings/backup").json()["cloud"]["pending"]
    assert pending["provider"] == "dropbox" and pending["authorize_url"].startswith("https://www.dropbox.com/")
    wrong = owner_api.post("/settings/backup/cloud/dropbox/finish", {"code": "not-the-code-at-all"})
    assert wrong.status_code == 422 and wrong.json()["code"] == "cloud_bad_code"
    assert owner_api.get("/settings/backup").json()["cloud"]["pending"] is not None  # paste again

    r = owner_api.post("/settings/backup/cloud/dropbox/finish", {"code": CODE})
    assert r.status_code == 200, r.text
    root = "Backups/"
    assert dbx.tree() == {
        root,
        root + "snapshots/",
        root + "sealed/",
        root + f"sealed/{_sealed('a')}",
        root + "snapshots/20261120-030000/",
        *(root + f"snapshots/20261120-030000/{f}" for f in cloud.SNAPSHOT_FILES),
    }
    dump = dbx.items[dbx.find("Backups/snapshots/20261120-030000/" + cloud.backup.DUMP_SEALED)]
    assert dump["data"] == b"d" * 200 * 1024  # continued where the dropped piece stopped
    c = owner_api.get("/settings/backup").json()["cloud"]
    assert c["provider"] == "dropbox" and c["state"] == "ok" and c["backups"] == 1 and c["free_bytes"] is None
    history = [h for h in owner_api.get("/history").json() if h["type"] == "backup.cloud_connected"]
    assert history[0]["detail"] == "Dropbox"
    assert REFRESH.encode() not in settings.backup_settings_file.read_bytes()
    assert (settings.secrets_dir / "cloud-dropbox.bin").exists()
    assert not list(settings.secrets_dir.glob("*pending*"))  # the verifier is gone once used
    _no_secrets(json.dumps(c), r.text, owner_api.get("/history").text)

    # The next backup is copied; the oldest one leaves with the local folder.
    _snapshot("20261121-030000", [_sealed("a")])
    assert cloud.due() and cloud.copy_if_due()
    assert root + "snapshots/20261121-030000/manifest.json" in dbx.tree()


def test_an_expired_sign_in_starts_over(owner_api: Api, dbx: FakeDropbox, frozen: FrozenClock) -> None:
    _encryption_on()
    _authorize(dbx, owner_api.post("/settings/backup/cloud/dropbox/start"))
    frozen.advance(minutes=31)
    r = owner_api.post("/settings/backup/cloud/dropbox/finish", {"code": CODE})
    assert r.status_code == 409 and r.json()["code"] == "cloud_expired"
    assert owner_api.get("/settings/backup").json()["cloud"]["pending"] is None


def test_a_full_dropbox_and_withdrawn_access_are_said_plainly(
    owner_api: Api, dbx: FakeDropbox, frozen: FrozenClock
) -> None:
    _encryption_on()
    _snapshot("20261120-030000", [])
    dbx.limit = 10
    _connect_backups(owner_api, dbx)
    c = owner_api.get("/settings/backup").json()["cloud"]
    assert c["state"] == "failing" and c["error"]["code"] == "no_room" and "Dropbox is full" in c["error"]["message"]
    dbx.limit = None
    frozen.advance(hours=21)
    assert cloud.copy_if_due() and owner_api.get("/settings/backup").json()["cloud"]["state"] == "ok"

    dbx.revoked = True
    _snapshot("20261121-030000", [])
    assert cloud.copy_if_due()
    assert owner_api.get("/settings/backup").json()["cloud"]["state"] == "revoked"
    item = cloud.attention_item()
    assert item is not None and item["text"].startswith("Dropbox no longer allows RecallSpring")


def test_disconnect_deletes_only_what_recallspring_made(owner_api: Api, dbx: FakeDropbox) -> None:
    _encryption_on()
    _snapshot("20261120-030000", [])
    dbx.items["id:mine"] = {"name": "my own notes.txt", "parent": "", "folder": False, "data": b"x"}
    _connect_backups(owner_api, dbx)
    google = owner_api.post("/settings/backup/cloud/google/start")
    assert google.status_code == 409 and google.json()["code"] == "cloud_connected"  # one at a time
    r = owner_api.post("/settings/backup/cloud/disconnect", {"delete_files": True})
    assert r.status_code == 200 and r.json()["cloud"]["state"] == "off"
    assert dbx.tree() == {"my own notes.txt"} and dbx.revoke_calls == 1
    assert not cloud._token_path("dropbox").exists()


# ---------------------------------------------------------------- a learner's own cloud folder


def test_material_goes_to_dropbox_by_course_and_follows_renames(owner_api: Api, dbx: FakeDropbox) -> None:
    cid = owner_api.post("/courses", {"title": "Biology"}).json()["id"]
    off = owner_api.get("/drive").json()
    assert off["available"] == {"google": False, "dropbox": True} and off["provider"] is None
    v = _connect_folder(owner_api, dbx)
    assert v["provider"] == "dropbox" and v["folder"] == "Dropbox › Apps › RecallSpring › Material"
    assert owner_api.post("/drive/start").json()["code"] == "drive_connected"  # one at a time

    _upload(owner_api, cid, "Mitoza – povzetek.txt", b"Prophase, metaphase.", "Week 1")
    _upload(owner_api, cid, "mitoza – POVZETEK.txt", b"Same name, other case.", "Week 1")
    assert my_drive.sync_all() == 1
    week = "Material/Biology/Week 1/"
    assert {week + "Mitoza – povzetek.txt", week + "mitoza – POVZETEK (1).txt"} <= dbx.tree()

    with new_session() as db:  # renamed in RecallSpring: moved in Dropbox
        course = db.get(Course, uuid.UUID(cid))
        assert course is not None
        course.title = "Cell Biology"
        db.commit()
    _upload(owner_api, cid, "b.txt", b"b", "Week 1")
    my_drive.sync_all()
    assert dbx.moves == 1 and "Material/Cell Biology/Week 1/b.txt" in dbx.tree()
    assert "Material/Biology/" not in dbx.tree()

    dbx.remove(dbx.find("Material/Cell Biology/Week 1"))  # deleted in Dropbox: made again, copied again
    _upload(owner_api, cid, "c.txt", b"c", "Week 1")
    my_drive.sync_all()
    my_drive.sync_all()
    assert {"Material/Cell Biology/Week 1/c.txt", "Material/Cell Biology/Week 1/b.txt"} <= dbx.tree()

    history = owner_api.get("/history").json()
    connected = next(h for h in history if h["type"] == "drive.connected")
    assert connected["text"] == "Your cloud folder connected" and connected["detail"] == "Dropbox"
    gone = owner_api.post("/drive/disconnect", {"delete_files": True})
    assert gone.status_code == 200 and dbx.tree() == set() and dbx.revoke_calls == 1
    _no_secrets(json.dumps(v), gone.text, json.dumps(history))


def test_withdrawn_dropbox_shows_in_today(owner_api: Api, dbx: FakeDropbox) -> None:
    cid = owner_api.post("/courses", {"title": "Physics"}).json()["id"]
    _connect_folder(owner_api, dbx)
    dbx.revoked = True
    _upload(owner_api, cid, "a.txt", b"a")
    my_drive.sync_all()
    v = owner_api.get("/drive").json()
    assert v["state"] == "revoked" and v["error"]["message"].startswith("Dropbox no longer allows")
    waiting = owner_api.get("/dashboard").json()["attention"]
    assert any(a["kind"] == "drive" and a["title"] == "Your Dropbox copy stopped" for a in waiting)
