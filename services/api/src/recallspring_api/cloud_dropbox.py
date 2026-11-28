"""Dropbox for the cloud copy of backups (cloud.py) and for a learner's own cloud folder (services/my_drive.py),
decided 2026-11-28.

- The Dropbox app is registered once by whoever runs RecallSpring, with **App folder** access: RecallSpring sees only
  ``Dropbox/Apps/<app name>/`` and nothing else in the account. Only its App key is needed (RS_CLOUD_DROPBOX_APP_KEY,
  from the server settings, never from Git): the sign-in uses PKCE, so there is no app secret.
- Sign-in without a return address: RecallSpring opens dropbox.com/oauth2/authorize, the learner allows it and
  Dropbox shows a code, which the learner pastes back. The PKCE verifier stays on the server.
- Scopes: files.metadata.read and files.content.write only. RecallSpring never asks for account details, so the free
  room is not shown; a full Dropbox is reported when an upload is refused.
- Items are referred to by Dropbox file ids (``id:…``), so a folder moved or renamed in Dropbox is still found. Paths
  are looked up from the id when one is needed (making a folder or a file inside it), once per run.
- Errors are told by their ``.tag`` (insufficient_space, not_found, conflict, incorrect_offset), never by the free text.

API reference: docs.dropboxapi.com (OAuth guide, files/upload, files/upload_session/*, files/list_folder,
files/create_folder_v2, files/delete_v2, files/get_metadata, files/move_v2, auth/token/revoke), read 2026-11-28.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from .cloud import CloudError

AUTHORIZE = "https://www.dropbox.com/oauth2/authorize"
TOKEN = "https://api.dropboxapi.com/oauth2/token"
API = "https://api.dropboxapi.com/2"
CONTENT = "https://content.dropboxapi.com/2"
SCOPES = "files.metadata.read files.content.write"
CHUNK = 2 * 4 * 1024 * 1024  # 8 MiB: every piece but the last must be a multiple of 4 MiB; one request at most 150 MiB
LABEL = "Dropbox"

REVOKED = "Dropbox no longer allows RecallSpring. Your backups are still made on this computer."


# ---------------------------------------------------------------- sign-in (PKCE, code shown by Dropbox)


def new_pkce() -> tuple[str, str]:
    """(verifier, S256 challenge). The verifier stays on the server."""
    verifier = secrets.token_urlsafe(64)  # 86 characters, within 43-128
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(app_key: str, challenge: str) -> str:
    """No redirect_uri: Dropbox shows the code to copy. ``offline`` gives a refresh token."""
    return f"{AUTHORIZE}?" + urlencode(
        {
            "client_id": app_key,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "token_access_type": "offline",
            "scope": SCOPES,
        }
    )


def exchange(http: httpx.Client, app_key: str, code: str, verifier: str) -> dict[str, Any]:
    """The pasted code for a refresh token (and a first access token)."""
    data = {"code": code, "grant_type": "authorization_code", "code_verifier": verifier, "client_id": app_key}
    try:
        r = http.post(TOKEN, data=data)
    except httpx.HTTPError as exc:
        raise CloudError("unreachable", "Could not reach Dropbox. Check the connection and try again.") from exc
    if r.status_code == 200 and r.json().get("refresh_token"):
        return dict(r.json())
    if r.status_code == 400:
        raise CloudError(
            "bad_code",
            "Dropbox did not accept that code. Copy the whole code again, or start over for a new one.",
        )
    raise CloudError("refused", "Dropbox did not sign in. Check the App key in the server settings.")


# ---------------------------------------------------------------- calls


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _tags(r: httpx.Response) -> str:
    """The error's .tag values, joined (e.g. "path/insufficient_space"), from the JSON, not the free text."""
    try:
        body = r.json()
    except ValueError:
        return ""
    found: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, dict):
            if isinstance(v.get(".tag"), str):
                found.append(v[".tag"])
            for k, x in v.items():
                if k != ".tag":
                    walk(x)

    walk(body.get("error") if isinstance(body, dict) else None)
    return "/".join(found)


def _check(r: httpx.Response) -> httpx.Response:
    if r.status_code < 400:
        return r
    tags = _tags(r)
    if r.status_code == 409 and "insufficient_space" in tags:
        raise CloudError("no_room", "Your Dropbox is full. RecallSpring tries again tomorrow.")
    if r.status_code == 409 and "not_found" in tags:
        raise CloudError("missing", "A folder RecallSpring made in Dropbox is gone. RecallSpring makes it again.")
    if r.status_code == 409 and "conflict" in tags:
        raise CloudError("conflict", "Something with that name is in the way in Dropbox.")
    if r.status_code == 401 and "expired_access_token" not in tags:
        raise CloudError("revoked", REVOKED)
    if r.status_code == 429:
        raise CloudError("unreachable", "Dropbox asked RecallSpring to slow down. RecallSpring tries again later.")
    raise CloudError("unreachable", "Dropbox did not answer as expected. RecallSpring tries again later.")


class Dropbox:
    """One per run: it remembers the paths it looked up."""

    name = "dropbox"
    label = LABEL
    backup_root = "Backups"  # in Dropbox/Apps/<app name>/
    drive_root = "Material"
    where = "Dropbox › Apps › RecallSpring"

    def __init__(self, app_key: str) -> None:
        self.app_key = app_key
        self.paths: dict[str, str] = {}

    # -- tokens

    def access_token(self, http: httpx.Client, token_file: Path) -> str:
        from . import cloud

        token = cloud._read_secret(token_file)
        if not token:
            raise CloudError("revoked", "Dropbox is not connected any more. Connect it again in Settings.")
        data = {"grant_type": "refresh_token", "refresh_token": token["refresh_token"], "client_id": self.app_key}
        try:
            r = http.post(TOKEN, data=data)
        except httpx.HTTPError as exc:
            raise CloudError("unreachable", "Could not reach Dropbox. RecallSpring tries again later.") from exc
        if r.status_code in (400, 401):
            raise CloudError("revoked", REVOKED)
        if r.status_code != 200:
            raise CloudError("unreachable", "Dropbox did not answer as expected. RecallSpring tries again later.")
        return str(r.json()["access_token"])

    def revoke(self, http: httpx.Client, token_file: Path) -> None:
        """Ask Dropbox to withdraw the sign-in (this disables the refresh token too)."""
        access = self.access_token(http, token_file)
        http.post(f"{API}/auth/token/revoke", headers=_auth(access))

    # -- metadata

    def _rpc(self, http: httpx.Client, token: str, endpoint: str, args: dict[str, Any]) -> dict[str, Any]:
        r = http.post(f"{API}/{endpoint}", json=args, headers=_auth(token))
        return dict(_check(r).json())

    def get(self, http: httpx.Client, token: str, ref: str) -> dict[str, Any] | None:
        """{id, name, trashed} or None when it is gone (deleted files are not found)."""
        try:
            m = self._rpc(http, token, "files/get_metadata", {"path": ref})
        except CloudError as exc:
            if exc.code == "missing":
                return None
            raise
        self.paths[m["id"]] = m["path_display"]
        return {"id": m["id"], "name": m["name"], "trashed": False}

    def _path(self, http: httpx.Client, token: str, ref: str | None) -> str:
        if not ref:
            return ""  # the app folder itself
        if ref.startswith("/"):
            return ref
        if ref not in self.paths:
            m = self._rpc(http, token, "files/get_metadata", {"path": ref})
            self.paths[ref] = m["path_display"]
        return self.paths[ref]

    def children(self, http: httpx.Client, token: str, parent: str) -> dict[str, dict[str, Any]]:
        """name -> {id, size, folder} of what is directly in a folder."""
        found: dict[str, dict[str, Any]] = {}
        body = self._rpc(http, token, "files/list_folder", {"path": parent, "limit": 2000})
        parent_path: str | None = None
        while True:
            for e in body.get("entries", []):
                found[e["name"]] = {
                    "id": e["id"],
                    "size": int(e.get("size") or 0),
                    "folder": e.get(".tag") == "folder",
                }
                if parent_path is None and e.get("path_display"):
                    parent_path = e["path_display"].rsplit("/", 1)[0]
            if not body.get("has_more"):
                break
            body = self._rpc(http, token, "files/list_folder/continue", {"cursor": body["cursor"]})
        if parent_path is not None and not parent.startswith("/"):
            self.paths.setdefault(parent, parent_path)
        return found

    def ensure_folder(self, http: httpx.Client, token: str, name: str, parent: str | None) -> str:
        """The folder's id, made when it is not there."""
        path = f"{self._path(http, token, parent)}/{name}"
        try:
            m = self._rpc(http, token, "files/create_folder_v2", {"path": path, "autorename": False})["metadata"]
        except CloudError as exc:
            if exc.code != "conflict":
                raise
            m = self._rpc(http, token, "files/get_metadata", {"path": path})
            if m.get(".tag") != "folder":
                raise CloudError("conflict", f"A file named {name} is in the way in Dropbox.") from exc
        self.paths[m["id"]] = m["path_display"]
        return str(m["id"])

    def new_folder(self, http: httpx.Client, token: str, name: str, parent: str) -> str:
        """A new folder; a name that is taken gets a number, as Dropbox does it ("Notes (1)")."""
        path = f"{self._path(http, token, parent)}/{name}"
        m = self._rpc(http, token, "files/create_folder_v2", {"path": path, "autorename": True})["metadata"]
        self.paths[m["id"]] = m["path_display"]
        return str(m["id"])

    def rename(self, http: httpx.Client, token: str, ref: str, name: str) -> None:
        m = self._rpc(http, token, "files/get_metadata", {"path": ref})
        parent = m["path_display"].rsplit("/", 1)[0]
        moved = self._rpc(
            http,
            token,
            "files/move_v2",
            {"from_path": m["path_lower"], "to_path": f"{parent}/{name}", "autorename": True},
        )["metadata"]
        self.paths = {}  # paths under it changed
        self.paths[moved["id"]] = moved["path_display"]

    def delete(self, http: httpx.Client, token: str, ref: str) -> None:
        try:
            self._rpc(http, token, "files/delete_v2", {"path": ref})
        except CloudError as exc:
            if exc.code != "missing":
                raise
        self.paths.pop(ref, None)

    def free_bytes(self, http: httpx.Client, token: str) -> int | None:
        return None  # would need account_info.read; not asked for (2026-11-28)

    # -- upload

    def _content(
        self, http: httpx.Client, token: str, endpoint: str, args: dict[str, Any], data: bytes
    ) -> httpx.Response:
        headers = _auth(token) | {
            "Content-Type": "application/octet-stream",
            "Dropbox-API-Arg": json.dumps(args, ensure_ascii=True),  # non-ASCII must be \\u-escaped in the header
        }
        return http.post(f"{CONTENT}/{endpoint}", content=data, headers=headers)

    def upload(
        self,
        http: httpx.Client,
        token: str,
        path: Path,
        parent: str,
        on_bytes: Callable[[int], None],
        name: str | None = None,
        file_id: list[str] | None = None,
    ) -> int:
        """Up to CHUNK in one request; larger files in an upload session, continuing after a dropped piece (Dropbox
        says where it got to). A name that is taken gets a number. Returns the size Dropbox reports."""
        size = path.stat().st_size
        commit = {"path": f"{self._path(http, token, parent)}/{name or path.name}", "mode": "add", "autorename": True}
        with path.open("rb") as fh:
            if size <= CHUNK:
                meta = self._single(http, token, commit, fh.read())
                on_bytes(size)
            else:
                meta = self._session(http, token, commit, fh, size, on_bytes)
        if file_id is not None:
            file_id.append(str(meta.get("id") or ""))
        return int(meta.get("size") or 0)

    def _single(self, http: httpx.Client, token: str, commit: dict[str, Any], data: bytes) -> dict[str, Any]:
        for drops in range(4):
            try:
                return dict(_check(self._content(http, token, "files/upload", commit | {"mute": True}, data)).json())
            except httpx.HTTPError:
                if drops == 3:
                    raise CloudError("unreachable", "The connection to Dropbox kept dropping.") from None
        raise AssertionError("unreachable")  # pragma: no cover

    def _session(
        self,
        http: httpx.Client,
        token: str,
        commit: dict[str, Any],
        fh: Any,
        size: int,
        on_bytes: Callable[[int], None],
    ) -> dict[str, Any]:
        session: str | None = None
        offset = 0
        drops = 0
        while True:
            fh.seek(offset)
            piece = fh.read(CHUNK)
            last = offset + len(piece) >= size
            try:
                if session is None:
                    r = self._content(http, token, "files/upload_session/start", {"close": False}, piece)
                elif last:
                    cursor = {"session_id": session, "offset": offset}
                    r = self._content(
                        http,
                        token,
                        "files/upload_session/finish",
                        {"cursor": cursor, "commit": commit | {"mute": True}},
                        piece,
                    )
                else:
                    cursor = {"session_id": session, "offset": offset}
                    r = self._content(
                        http, token, "files/upload_session/append_v2", {"cursor": cursor, "close": False}, piece
                    )
            except httpx.HTTPError:
                drops += 1
                if drops > 3:
                    raise CloudError("unreachable", "The connection to Dropbox kept dropping.") from None
                continue  # send the same piece again; if part of it arrived, Dropbox says where it got to
            if session is not None and r.status_code == 409 and "incorrect_offset" in _tags(r):
                correct = _correct_offset(r)
                on_bytes(correct - offset)
                offset = correct
                continue
            body = _check(r).json()
            if session is None:
                session = str(body["session_id"])
            elif last:
                on_bytes(len(piece))
                return dict(body)
            on_bytes(len(piece))
            offset += len(piece)


def _correct_offset(r: httpx.Response) -> int:
    def find(v: Any) -> int | None:
        if isinstance(v, dict):
            if isinstance(v.get("correct_offset"), int):
                return int(v["correct_offset"])
            for x in v.values():
                if (got := find(x)) is not None:
                    return got
        return None

    got = find(r.json())
    if got is None:
        raise CloudError("unreachable", "Dropbox did not answer as expected. RecallSpring tries again later.")
    return got
