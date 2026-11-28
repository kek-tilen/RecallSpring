"""OneDrive (2026-11-28), against a fake Microsoft sign-in and a fake OneDrive (Microsoft Graph): the cloud copy of
backups and a learner's own cloud folder go to the app folder only, the sign-in is a code typed at Microsoft (no app
secret, the device code never reaches the browser), a school that blocks this sign-in or refuses the app folder is
said plainly and nothing wider is ever asked for, the newest refresh token is kept, large files go in an upload
session and continue after a drop, names OneDrive refuses are changed, renamed and deleted folders are followed, and
Disconnect deletes only what RecallSpring made. No secret in any view, file or History."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote

import httpx
import pytest
from sqlalchemy import select

from recallspring_api import cloud, cloud_onedrive
from recallspring_api.cloud_onedrive import safe_name
from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent, Course
from recallspring_api.services import my_drive

from .conftest import Api, FrozenClock
from .test_cloud_copy import _encryption_on, _sealed, _snapshot
from .test_my_drive import _upload

CLIENT = "00000000-test-onedrive-client"
DEVICE = "ms-fake-device-code-never-shown"
REFRESH = "ms-fake-refresh-token-1"
APPROOT = "approot-id"


def _err(status: int, code: str, **extra: Any) -> httpx.Response:
    return httpx.Response(status, json={"error": {"code": code, "message": code}, **extra})


class FakeOneDrive:
    """Just enough of Microsoft's device-code sign-in and Graph's drive API for cloud_onedrive.py."""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}  # id -> {name, parent, folder, data}; parent APPROOT = app folder
        self.sessions: dict[str, dict[str, Any]] = {}
        self.approve: str | None = None  # None (still waiting), "yes", "blocked", "declined"
        self.business = False  # a school account that refuses the app folder
        self.revoked = False
        self.refresh = REFRESH
        self.refreshes = 0
        self.scopes_asked: list[str] = []
        self.limit: int | None = None
        self.quota: int | None = 5 * 1024**3
        self.drop_next_piece = False
        self.page = 1000
        self.n = 0

    # -- the tree

    def _id(self) -> str:
        self.n += 1
        return f"item{self.n:04d}"

    def _child(self, parent: str, name: str) -> str | None:
        return next(
            (k for k, v in self.items.items() if v["parent"] == parent and v["name"].lower() == name.lower()), None
        )

    def _free_name(self, parent: str, name: str) -> str:
        if self._child(parent, name) is None:
            return name
        stem, dot, ext = name.rpartition(".") if "." in name else (name, "", "")
        i = 1
        while self._child(parent, f"{stem} {i}{dot}{ext}") is not None:
            i += 1
        return f"{stem} {i}{dot}{ext}"

    def tree(self, parent: str = APPROOT, prefix: str = "") -> set[str]:
        out: set[str] = set()
        for fid, f in self.items.items():
            if f["parent"] == parent:
                p = f"{prefix}{f['name']}"
                out |= {p + "/"} | self.tree(fid, p + "/") if f["folder"] else {p}
        return out

    def find(self, path: str) -> str:
        cur = APPROOT
        for part in path.strip("/").split("/"):
            nxt = self._child(cur, part)
            assert nxt, path
            cur = nxt
        return cur

    def remove(self, fid: str) -> None:
        for child in [k for k, v in self.items.items() if v["parent"] == fid]:
            self.remove(child)
        self.items.pop(fid, None)

    def meta(self, fid: str) -> dict[str, Any]:
        f = self.items[fid]
        m: dict[str, Any] = {"id": fid, "name": f["name"]}
        return m | ({"folder": {"childCount": 0}} if f["folder"] else {"size": len(f["data"]), "file": {}})

    def _write(self, parent: str, name: str, data: bytes) -> httpx.Response:
        used = sum(len(v.get("data", b"")) for v in self.items.values())
        if self.limit is not None and used + len(data) > self.limit:
            return _err(507, "quotaLimitReached")
        fid = self._id()
        self.items[fid] = {"name": self._free_name(parent, name), "parent": parent, "folder": False, "data": data}
        return httpx.Response(201, json=self.meta(fid))

    # -- requests

    def handler(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "login.microsoftonline.com":
            return self._login(request)
        if host == "upload.fake":
            assert "authorization" not in request.headers  # the upload URL carries its own authorisation
            return self._piece(request)
        assert host == "graph.microsoft.com"
        assert request.headers.get("authorization") == "Bearer at"
        raw = request.url.raw_path.decode().split("?", 1)[0]
        assert raw.startswith("/v1.0/me/drive"), raw
        rest = raw[len("/v1.0/me/drive") :]
        if rest == "/special/approot":
            return _err(403, "accessDenied") if self.business else httpx.Response(200, json={"id": APPROOT})
        if rest == "":
            if self.quota is None:
                return _err(403, "accessDenied")
            return httpx.Response(200, json={"quota": {"remaining": self.quota, "total": 5 * 1024**3}})
        m = re.fullmatch(r"/items/([^/:]+)(?::/([^:]+):)?(/children|/content|/createUploadSession)?", rest)
        assert m, rest
        ref, name, tail = unquote(m.group(1)), m.group(2), m.group(3)
        if name is not None:
            return self._by_name(request, ref, unquote(name), tail)
        if ref != APPROOT and ref not in self.items:
            return _err(404, "itemNotFound")
        if tail == "/children" and request.method == "GET":
            kids = [self.meta(k) for k, v in self.items.items() if v["parent"] == ref]
            start = int(request.url.params.get("skip", "0"))
            body: dict[str, Any] = {"value": kids[start : start + self.page]}
            if start + self.page < len(kids):
                body["@odata.nextLink"] = (
                    f"https://graph.microsoft.com/v1.0/me/drive/items/{ref}/children?skip={start + self.page}"
                )
            return httpx.Response(200, json=body)
        if tail == "/children" and request.method == "POST":
            args = json.loads(request.content)
            assert "folder" in args
            if self._child(ref, args["name"]) is not None and args["@microsoft.graph.conflictBehavior"] == "fail":
                return _err(409, "nameAlreadyExists")
            fid = self._id()
            self.items[fid] = {"name": self._free_name(ref, args["name"]), "parent": ref, "folder": True}
            return httpx.Response(201, json=self.meta(fid))
        if request.method == "GET":
            return httpx.Response(200, json=self.meta(ref))
        if request.method == "PATCH":
            new = json.loads(request.content)["name"]
            other = self._child(self.items[ref]["parent"], new)
            if other is not None and other != ref:
                return _err(409, "nameAlreadyExists")
            self.items[ref]["name"] = new
            return httpx.Response(200, json=self.meta(ref))
        if request.method == "DELETE":
            self.remove(ref)
            return httpx.Response(204)
        raise AssertionError(f"unexpected {request.method} {request.url}")

    def _by_name(self, request: httpx.Request, parent: str, name: str, tail: str | None) -> httpx.Response:
        assert name == safe_name(name), name  # only names OneDrive accepts are sent
        if tail is None and request.method == "GET":
            fid = self._child(parent, name)
            return httpx.Response(200, json=self.meta(fid)) if fid else _err(404, "itemNotFound")
        if tail == "/content" and request.method == "PUT":
            assert request.url.params.get("@microsoft.graph.conflictBehavior") == "rename"
            return self._write(parent, name, request.content)
        if tail == "/createUploadSession":
            assert json.loads(request.content)["item"]["@microsoft.graph.conflictBehavior"] == "rename"
            sid = f"s{len(self.sessions) + 1}"
            self.sessions[sid] = {"parent": parent, "name": name, "data": bytearray()}
            return httpx.Response(200, json={"uploadUrl": f"https://upload.fake/{sid}"})
        raise AssertionError(f"unexpected {request.method} {request.url}")

    def _piece(self, request: httpx.Request) -> httpx.Response:
        s = self.sessions[request.url.path.strip("/")]
        got: bytearray = s["data"]
        if request.method == "GET":
            return httpx.Response(200, json={"nextExpectedRanges": [f"{len(got)}-"]})
        start, end, size = map(int, re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", request.headers["content-range"]).groups())
        assert end - start + 1 == len(request.content)
        if start != len(got):
            return _err(416, "invalidRange")
        if self.drop_next_piece and start > 0:
            self.drop_next_piece = False
            got.extend(request.content[: len(request.content) // 2])  # half arrived, then the line dropped
            raise httpx.ConnectError("dropped")
        got.extend(request.content)
        if len(got) < size:
            return httpx.Response(202, json={"nextExpectedRanges": [f"{len(got)}-"]})
        return self._write(s["parent"], s["name"], bytes(got))

    def _login(self, request: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        assert form["client_id"] == CLIENT and "client_secret" not in form  # a public client: no secret
        if request.url.path.endswith("/devicecode"):
            self.scopes_asked.append(form["scope"])
            return httpx.Response(
                200,
                json={
                    "device_code": DEVICE,
                    "user_code": "FAKE1234",
                    "verification_uri": "https://microsoft.com/devicelogin",
                    "expires_in": 900,
                    "interval": 5,
                    "message": "To sign in, use a web browser…",
                },
            )
        if form["grant_type"] == "urn:ietf:params:oauth:grant-type:device_code":
            assert form["device_code"] == DEVICE
            if self.approve is None:
                return httpx.Response(400, json={"error": "authorization_pending"})
            if self.approve == "blocked":
                return httpx.Response(
                    400,
                    json={
                        "error": "invalid_grant",
                        "error_description": "AADSTS53003: Access has been blocked by Conditional Access policies.",
                        "error_codes": [53003],
                    },
                )
            if self.approve == "declined":
                return httpx.Response(400, json={"error": "authorization_declined"})
            return httpx.Response(200, json={"access_token": "at", "refresh_token": self.refresh, "expires_in": 3600})
        assert form["grant_type"] == "refresh_token" and form["scope"] == cloud_onedrive.SCOPES
        if self.revoked or form["refresh_token"] != self.refresh:
            return httpx.Response(400, json={"error": "invalid_grant"})
        self.refreshes += 1
        self.refresh = f"ms-fake-refresh-token-{self.refreshes + 1}"  # Microsoft sends a new one each time
        return httpx.Response(200, json={"access_token": "at", "refresh_token": self.refresh, "expires_in": 3600})


@pytest.fixture
def od(settings: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeOneDrive]:
    fake = FakeOneDrive()
    monkeypatch.setattr(settings, "backup_enabled", True)
    monkeypatch.setattr(settings, "backup_dir", tmp_path / "backups")
    monkeypatch.setattr(settings, "backup_settings_file", tmp_path / "backup-settings.json")
    monkeypatch.setattr(settings, "backup_settings_from_web", True)
    monkeypatch.setattr(settings, "run_dir", tmp_path / "run")
    monkeypatch.setattr(settings, "secrets_dir", tmp_path / "secrets")
    monkeypatch.setattr(settings, "cloud_google_client_id", None)
    monkeypatch.setattr(settings, "cloud_dropbox_app_key", None)
    monkeypatch.setattr(settings, "cloud_onedrive_client_id", CLIENT)
    monkeypatch.setattr(cloud, "_transport", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(cloud, "_spawn", lambda f: f())  # copies run inline in tests
    monkeypatch.setattr(cloud_onedrive, "CHUNK", 64 * 1024)  # small pieces in tests (320 KiB multiples in real use)
    monkeypatch.setattr(cloud_onedrive, "SIMPLE_MAX", 64 * 1024)
    yield fake


def _audit_text() -> str:
    with new_session() as db:
        return json.dumps([e.details for e in db.scalars(select(AuditEvent))], default=str)


def _no_secrets(fake: FakeOneDrive, *texts: str) -> None:
    for t in (*texts, _audit_text()):
        assert DEVICE not in t and "ms-fake-refresh-token" not in t


def _sign_in(
    api: Api, fake: FakeOneDrive, frozen: FrozenClock, start: str, poll: str, outcome: str = "yes"
) -> httpx.Response:
    """Start, see the code, check once while the learner is still signing in, then once after they finished."""
    fake.approve = None
    r = api.post(start)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "onedrive" and body["user_code"] == "FAKE1234" and DEVICE not in r.text
    assert body["verification_url"] == "https://microsoft.com/devicelogin"
    assert api.post(poll).json()["state"] == "pending"
    fake.approve = outcome
    frozen.advance(seconds=6)
    return api.post(poll)


def _connect_backups(api: Api, fake: FakeOneDrive, frozen: FrozenClock) -> dict[str, Any]:
    r = _sign_in(api, fake, frozen, "/settings/backup/cloud/onedrive/start", "/settings/backup/cloud/onedrive/poll")
    assert r.status_code == 200 and r.json()["state"] == "connected", r.text
    return r.json()["backup"]


def _connect_folder(api: Api, fake: FakeOneDrive, frozen: FrozenClock) -> dict[str, Any]:
    r = _sign_in(api, fake, frozen, "/drive/onedrive/start", "/drive/poll")
    assert r.status_code == 200 and r.json()["state"] == "connected", r.text
    return r.json()["drive"]


# ---------------------------------------------------------------- names


def test_safe_names() -> None:
    assert safe_name("Mitoza – povzetek.txt") == "Mitoza – povzetek.txt"
    assert safe_name('a:b*c?"d<e>f|g.txt') == "a_b_c__d_e_f_g.txt"
    assert safe_name("~$draft.docx") == "_draft.docx"
    assert safe_name("CON.txt") == "_CON.txt" and safe_name("desktop.ini") == "_desktop.ini"
    assert safe_name("notes. ") == "notes" and safe_name("   ") == "_"
    long = safe_name("x" * 300 + ".pdf")
    assert len(long) == 250 and long.endswith(".pdf")


# ---------------------------------------------------------------- cloud copy of backups


def test_backups_go_to_the_onedrive_app_folder_after_a_code(
    owner_api: Api, od: FakeOneDrive, settings: Any, frozen: FrozenClock
) -> None:
    view = owner_api.get("/settings/backup").json()["cloud"]
    assert view["available"] == {"google": False, "dropbox": False, "onedrive": True}
    assert owner_api.post("/settings/backup/cloud/onedrive/start").json()["code"] == "cloud_needs_encryption"
    _encryption_on()
    _snapshot("20261120-030000", [_sealed("a"), _sealed("b"), _sealed("c")], size=200 * 1024)  # an upload session
    od.drop_next_piece = True
    od.page = 2  # the sealed folder's listing comes in pages

    r = _sign_in(owner_api, od, frozen, "/settings/backup/cloud/onedrive/start", "/settings/backup/cloud/onedrive/poll")
    assert r.status_code == 200 and r.json()["state"] == "connected", r.text
    assert od.scopes_asked == ["Files.ReadWrite.AppFolder offline_access"]  # never more
    root = "Backups/"
    assert root + "snapshots/20261120-030000/" + cloud.backup.DUMP_SEALED in od.tree()
    assert {root + f"sealed/{_sealed(x)}" for x in "abc"} <= od.tree()
    dump = od.items[od.find("Backups/snapshots/20261120-030000/" + cloud.backup.DUMP_SEALED)]
    assert dump["data"] == b"d" * 200 * 1024  # continued where the dropped piece stopped
    c = owner_api.get("/settings/backup").json()["cloud"]
    assert c["provider"] == "onedrive" and c["state"] == "ok" and c["backups"] == 1
    assert c["free_bytes"] == od.quota
    history = [h for h in owner_api.get("/history").json() if h["type"] == "backup.cloud_connected"]
    assert history[0]["detail"] == "OneDrive"

    # The newest refresh token replaces the old one; none is in the settings file or a view.
    saved = cloud._read_secret(cloud._token_path("onedrive"))
    assert saved is not None and saved["refresh_token"] == od.refresh != REFRESH
    assert b"ms-fake-refresh-token" not in settings.backup_settings_file.read_bytes()
    assert not list(settings.secrets_dir.glob("*pending*"))
    _no_secrets(od, json.dumps(c), r.text, owner_api.get("/history").text)

    # Listing the sealed folder again (pages of 2) finds all three: nothing is uploaded twice.
    _snapshot("20261121-030000", [_sealed("a"), _sealed("b"), _sealed("c")])
    assert cloud.due() and cloud.copy_if_due()
    assert sum(1 for p in od.tree() if p.startswith(root + "sealed/") and p != root + "sealed/") == 3
    assert root + "snapshots/20261121-030000/manifest.json" in od.tree()


def test_a_blocked_or_declined_sign_in_is_said_plainly(owner_api: Api, od: FakeOneDrive, frozen: FrozenClock) -> None:
    _encryption_on()
    start, poll = "/settings/backup/cloud/onedrive/start", "/settings/backup/cloud/onedrive/poll"
    r = _sign_in(owner_api, od, frozen, start, poll, outcome="blocked")
    assert r.json()["state"] == "blocked" and r.json()["backup"]["cloud"]["pending"] is None
    r = _sign_in(owner_api, od, frozen, start, poll, outcome="declined")
    assert r.json()["state"] == "denied"
    assert cloud.connection() is None and not cloud._token_path("onedrive").exists()


def test_a_school_account_without_the_app_folder_is_not_supported(
    owner_api: Api, od: FakeOneDrive, frozen: FrozenClock
) -> None:
    _encryption_on()
    od.business = True
    r = _sign_in(owner_api, od, frozen, "/settings/backup/cloud/onedrive/start", "/settings/backup/cloud/onedrive/poll")
    assert r.status_code == 200 and r.json()["state"] == "not_supported", r.text
    assert cloud.connection() is None and not cloud._token_path("onedrive").exists()
    assert od.scopes_asked == ["Files.ReadWrite.AppFolder offline_access"]  # no wider access asked for instead

    r = _sign_in(owner_api, od, frozen, "/drive/onedrive/start", "/drive/poll")
    assert r.json()["state"] == "not_supported" and r.json()["drive"]["state"] == "off"
    assert set(od.scopes_asked) == {"Files.ReadWrite.AppFolder offline_access"}


def test_a_full_onedrive_withdrawn_access_and_disconnect(owner_api: Api, od: FakeOneDrive, frozen: FrozenClock) -> None:
    _encryption_on()
    _snapshot("20261120-030000", [])
    od.limit = 10
    od.quota = None  # Microsoft does not tell the room: none shown, a refused upload says it
    _connect_backups(owner_api, od, frozen)
    c = owner_api.get("/settings/backup").json()["cloud"]
    assert c["state"] == "failing" and c["error"]["code"] == "no_room" and "OneDrive is full" in c["error"]["message"]
    assert c["free_bytes"] is None
    od.limit = None
    frozen.advance(hours=21)
    assert cloud.copy_if_due() and owner_api.get("/settings/backup").json()["cloud"]["state"] == "ok"

    od.items["mine"] = {"name": "my own notes.txt", "parent": APPROOT, "folder": False, "data": b"x"}
    r = owner_api.post("/settings/backup/cloud/disconnect", {"delete_files": True})
    assert r.status_code == 200 and r.json()["cloud"]["state"] == "off"
    assert od.tree() == {"my own notes.txt"} and not cloud._token_path("onedrive").exists()

    _connect_backups(owner_api, od, frozen)
    od.revoked = True
    _snapshot("20261121-030000", [])
    assert cloud.copy_if_due()
    assert owner_api.get("/settings/backup").json()["cloud"]["state"] == "revoked"
    item = cloud.attention_item()
    assert item is not None and item["text"].startswith("OneDrive no longer allows RecallSpring")


# ---------------------------------------------------------------- a learner's own cloud folder


def test_material_goes_to_onedrive_by_course_with_safe_names(
    owner_api: Api, od: FakeOneDrive, frozen: FrozenClock, settings: Any
) -> None:
    cid = owner_api.post("/courses", {"title": "Biology"}).json()["id"]
    off = owner_api.get("/drive").json()
    assert off["available"] == {"google": False, "dropbox": False, "onedrive": True} and off["provider"] is None
    v = _connect_folder(owner_api, od, frozen)
    assert v["provider"] == "onedrive" and v["folder"] == "OneDrive › Apps › RecallSpring › Material"
    assert owner_api.post("/drive/dropbox/start").json()["code"] == "drive_connected"  # one at a time

    _upload(owner_api, cid, "Mitoza – povzetek.txt", b"Prophase, metaphase.", "Week 1")
    _upload(owner_api, cid, "mitoza – POVZETEK.txt", b"Same name, other case.", "Week 1")
    _upload(owner_api, cid, "~$draft.txt", b"Office lock-file name.", "Week 1")
    _upload(owner_api, cid, "big.txt", b"x" * 150 * 1024, "Week 1")  # an upload session
    assert my_drive.sync_all() == 1
    week = "Material/Biology/Week 1/"
    assert {
        week + "Mitoza – povzetek.txt",
        week + "mitoza – POVZETEK 1.txt",
        week + "_draft.txt",
        week + "big.txt",
    } <= od.tree()
    assert od.items[od.find(week + "big.txt")]["data"] == b"x" * 150 * 1024

    with new_session() as db:  # renamed in RecallSpring: renamed in OneDrive
        course = db.get(Course, uuid.UUID(cid))
        assert course is not None
        course.title = "Cell Biology"
        db.commit()
    _upload(owner_api, cid, "b.txt", b"b", "Week 1")
    my_drive.sync_all()
    assert "Material/Cell Biology/Week 1/b.txt" in od.tree() and "Material/Biology/" not in od.tree()

    od.remove(od.find("Material/Cell Biology/Week 1"))  # deleted in OneDrive: made again, copied again
    _upload(owner_api, cid, "c.txt", b"c", "Week 1")
    my_drive.sync_all()
    my_drive.sync_all()
    assert {"Material/Cell Biology/Week 1/c.txt", "Material/Cell Biology/Week 1/b.txt"} <= od.tree()

    history = owner_api.get("/history").json()
    connected = next(h for h in history if h["type"] == "drive.connected")
    assert connected["text"] == "Your cloud folder connected" and connected["detail"] == "OneDrive"
    (token_file,) = [p for p in settings.secrets_dir.glob("drive-*.bin") if "pending" not in p.name]
    saved = cloud._read_secret(token_file)
    assert saved is not None and saved["refresh_token"] == od.refresh != REFRESH  # the newest one is kept
    gone = owner_api.post("/drive/disconnect", {"delete_files": True})
    assert gone.status_code == 200 and od.tree() == set()
    _no_secrets(od, json.dumps(v), gone.text, json.dumps(history))


def test_withdrawn_onedrive_shows_in_today(owner_api: Api, od: FakeOneDrive, frozen: FrozenClock) -> None:
    cid = owner_api.post("/courses", {"title": "Physics"}).json()["id"]
    _connect_folder(owner_api, od, frozen)
    od.revoked = True
    _upload(owner_api, cid, "a.txt", b"a")
    my_drive.sync_all()
    v = owner_api.get("/drive").json()
    assert v["state"] == "revoked" and v["error"]["message"].startswith("OneDrive no longer allows")
    waiting = owner_api.get("/dashboard").json()["attention"]
    assert any(a["kind"] == "drive" and a["title"] == "Your OneDrive copy stopped" for a in waiting)
