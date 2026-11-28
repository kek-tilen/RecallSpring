"""OneDrive for the cloud copy of backups (cloud.py) and for a learner's own cloud folder (services/my_drive.py),
decided 2026-11-28.

- The app is registered once by whoever runs RecallSpring, in their own Microsoft Entra directory, for "accounts in
  any organizational directory and personal Microsoft accounts" (personal and school or work accounts), with public
  client flows allowed. Only its Application (client) ID is needed (RS_CLOUD_ONEDRIVE_CLIENT_ID, from the server
  settings, never from Git); there is no secret.
- Sign-in: the device authorization grant, as for Google: Microsoft shows a short code the learner types at
  microsoft.com/devicelogin on any device. Many schools block this sign-in (Microsoft recommends it); RecallSpring
  then says so plainly and connects nothing.
- Scope ``Files.ReadWrite.AppFolder`` and ``offline_access`` only: RecallSpring sees only its own folder,
  ``OneDrive/Apps/<app name>/``. Microsoft's pages disagree on whether school or work accounts allow this (2026-11-28);
  when one refuses, RecallSpring says the account is not supported and never asks for wider access.
- Microsoft gives a new refresh token with each access token; the newest is kept. A sign-in unused for about 90 days
  expires and shows as withdrawn. Microsoft has no call for an app to withdraw its own sign-in: Disconnect forgets it,
  and the learner can remove RecallSpring in their Microsoft account.
- OneDrive does not allow some characters and names; ``safe_name`` changes only those, and RecallSpring keeps the
  original name. A name that is taken gets a number ("Notes 1"), as OneDrive does it.

API reference: learn.microsoft.com (v2-oauth2-device-code, onedrive-sharepoint-appfolder, driveitem-get,
driveitem-list-children, driveitem-post-children, driveitem-update, driveitem-delete, driveitem-put-content,
driveitem-createuploadsession, drive-get), read 2026-11-28.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from .cloud import CloudError

AUTHORITY = "https://login.microsoftonline.com/common/oauth2/v2.0"
DEVICE = f"{AUTHORITY}/devicecode"
TOKEN = f"{AUTHORITY}/token"
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = "Files.ReadWrite.AppFolder offline_access"
CHUNK = 32 * 320 * 1024  # 10 MiB: pieces must be multiples of 320 KiB, under 60 MiB a request
SIMPLE_MAX = 4 * 1024 * 1024  # up to this, one PUT; larger files use an upload session
LABEL = "OneDrive"

REVOKED = "OneDrive no longer allows RecallSpring. Your backups are still made on this computer."
NOT_SUPPORTED = (
    "This school or work account does not let RecallSpring use its own folder in OneDrive. Use a personal Microsoft "
    "account, Google Drive or Dropbox."
)

_BAD = re.compile(r'["*:<>?/\\|\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", ".lock", "desktop.ini"}
_RESERVED |= {f"{d}{n}" for d in ("com", "lpt") for n in range(10)}


def safe_name(name: str) -> str:
    """A name OneDrive accepts: no " * : < > ? / \\ |, no trailing dot or space, no reserved name, at most 250
    characters (the extension kept). Other names stay as they are."""
    s = _BAD.sub("_", name).strip().rstrip(". ") or "_"
    if s.startswith("~$"):
        s = "_" + s[2:]
    s = s.replace("_vti_", "_vti-")
    if s.lower() in _RESERVED or s.split(".")[0].lower() in _RESERVED:
        s = "_" + s
    if len(s) > 250:
        stem, dot, ext = s.rpartition(".")
        s = (stem[: 249 - len(ext)] + "." + ext) if dot and len(ext) <= 10 else s[:250]
    return s


# ---------------------------------------------------------------- errors


def _code(r: httpx.Response) -> str:
    try:
        body = r.json()
    except ValueError:
        return ""
    err = body.get("error") if isinstance(body, dict) else None
    return str(err.get("code") or "") if isinstance(err, dict) else str(err or "")


def _check(r: httpx.Response) -> httpx.Response:
    if r.status_code < 400:
        return r
    code = _code(r)
    if r.status_code == 507 or code in ("quotaLimitReached", "insufficientStorage"):
        raise CloudError("no_room", "Your OneDrive is full. RecallSpring tries again tomorrow.")
    if r.status_code == 404:
        raise CloudError("missing", "A folder RecallSpring made in OneDrive is gone. RecallSpring makes it again.")
    if r.status_code == 409:
        raise CloudError("conflict", "Something with that name is in the way in OneDrive.")
    if r.status_code in (401, 403):
        raise CloudError("revoked", REVOKED)
    if r.status_code in (429, 503):
        raise CloudError("unreachable", "OneDrive asked RecallSpring to slow down. RecallSpring tries again later.")
    raise CloudError("unreachable", "OneDrive did not answer as expected. RecallSpring tries again later.")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _item(ref: str) -> str:
    return f"{GRAPH}/me/drive/items/{quote(ref, safe='')}"


def _child(parent: str, name: str) -> str:
    """Path-based address of ``name`` inside ``parent``: /items/{id}:/{name}:"""
    return f"{_item(parent)}:/{quote(name, safe='')}:"


def _numbered(name: str, n: int) -> str:
    stem, dot, ext = name.rpartition(".")
    return f"{stem} {n}.{ext}" if dot and stem else f"{name} {n}"


class OneDrive:
    """One per run: it remembers the app folder's id."""

    name = "onedrive"
    label = LABEL
    backup_root = "Backups"  # in OneDrive/Apps/<app name>/
    drive_root = "Material"
    where = "OneDrive › Apps › RecallSpring"

    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self.approot: str | None = None

    # -- tokens

    def access_token(self, http: httpx.Client, token_file: Path) -> str:
        """A fresh access token; Microsoft sends a new refresh token too, which replaces the old one."""
        from . import cloud

        token = cloud._read_secret(token_file)
        if not token:
            raise CloudError("revoked", "OneDrive is not connected any more. Connect it again in Settings.")
        data = {
            "client_id": self.client_id,
            "grant_type": "refresh_token",
            "refresh_token": token["refresh_token"],
            "scope": SCOPES,
        }
        try:
            r = http.post(TOKEN, data=data)
        except httpx.HTTPError as exc:
            raise CloudError("unreachable", "Could not reach OneDrive. RecallSpring tries again later.") from exc
        if r.status_code in (400, 401):
            raise CloudError("revoked", REVOKED)
        if r.status_code != 200:
            raise CloudError("unreachable", "OneDrive did not answer as expected. RecallSpring tries again later.")
        body = r.json()
        if body.get("refresh_token") and body["refresh_token"] != token["refresh_token"]:
            cloud._write_secret(token_file, token | {"refresh_token": body["refresh_token"]})
        return str(body["access_token"])

    def revoke(self, http: httpx.Client, token_file: Path) -> None:
        """Microsoft has no call for an app to withdraw its own sign-in; Disconnect forgets it (docs/08)."""

    # -- items

    def _root(self, http: httpx.Client, token: str) -> str:
        """The app folder (made by OneDrive on first use). A school or work account that refuses it is not
        supported."""
        if self.approot is None:
            r = http.get(f"{GRAPH}/me/drive/special/approot", params={"$select": "id"}, headers=_auth(token))
            if r.status_code in (400, 403) or (r.status_code == 401 and _code(r) == "accessDenied"):
                raise CloudError("not_supported", NOT_SUPPORTED)
            self.approot = str(_check(r).json()["id"])
        return self.approot

    def get(self, http: httpx.Client, token: str, ref: str) -> dict[str, Any] | None:
        """{id, name, trashed} or None when it is gone (deleted items are not found)."""
        r = http.get(_item(ref), params={"$select": "id,name"}, headers=_auth(token))
        if r.status_code == 404:
            return None
        m = _check(r).json()
        return {"id": m["id"], "name": m["name"], "trashed": False}

    def children(self, http: httpx.Client, token: str, parent: str) -> dict[str, dict[str, Any]]:
        """name -> {id, size, folder} of what is directly in a folder."""
        found: dict[str, dict[str, Any]] = {}
        url: str | None = f"{_item(parent)}/children"
        params: dict[str, Any] | None = {"$select": "id,name,size,folder", "$top": 999}
        while url:
            body = _check(http.get(url, params=params, headers=_auth(token))).json()
            for e in body.get("value", []):
                found[e["name"]] = {"id": e["id"], "size": int(e.get("size") or 0), "folder": "folder" in e}
            url, params = body.get("@odata.nextLink"), None
        return found

    def _make(self, http: httpx.Client, token: str, name: str, parent: str, behaviour: str) -> httpx.Response:
        body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": behaviour}
        return http.post(f"{_item(parent)}/children", json=body, headers=_auth(token))

    def ensure_folder(self, http: httpx.Client, token: str, name: str, parent: str | None) -> str:
        """The folder's id, made when it is not there (``parent`` None: in the app folder)."""
        parent = parent or self._root(http, token)
        name = safe_name(name)
        r = self._make(http, token, name, parent, "fail")
        if r.status_code != 409:
            return str(_check(r).json()["id"])
        m = _check(http.get(_child(parent, name), params={"$select": "id,folder"}, headers=_auth(token))).json()
        if "folder" not in m:
            raise CloudError("conflict", f"A file named {name} is in the way in OneDrive.")
        return str(m["id"])

    def new_folder(self, http: httpx.Client, token: str, name: str, parent: str) -> str:
        """A new folder; a name that is taken gets a number, as OneDrive does it."""
        return str(_check(self._make(http, token, safe_name(name), parent, "rename")).json()["id"])

    def rename(self, http: httpx.Client, token: str, ref: str, name: str) -> None:
        base = safe_name(name)
        for n in range(0, 21):
            r = http.patch(_item(ref), json={"name": _numbered(base, n) if n else base}, headers=_auth(token))
            if r.status_code != 409:
                _check(r)
                return
        raise CloudError("conflict", f"Too many items named {base} in OneDrive.")

    def delete(self, http: httpx.Client, token: str, ref: str) -> None:
        r = http.delete(_item(ref), headers=_auth(token))
        if r.status_code not in (200, 204, 404):
            _check(r)

    def free_bytes(self, http: httpx.Client, token: str) -> int | None:
        """The room left, when Microsoft tells it with this access (it may not for the app folder only)."""
        try:
            r = http.get(f"{GRAPH}/me/drive", params={"$select": "quota"}, headers=_auth(token))
        except httpx.HTTPError:
            return None
        if r.status_code != 200:
            return None
        remaining = (r.json().get("quota") or {}).get("remaining")
        return int(remaining) if isinstance(remaining, int) else None

    # -- upload

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
        """Up to 4 MiB in one request; larger files in an upload session of 10 MiB pieces, continuing after a dropped
        piece from where OneDrive says it got to. A name that is taken gets a number. Returns the size OneDrive
        reports."""
        size = path.stat().st_size
        target = _child(parent, safe_name(name or path.name))
        with path.open("rb") as fh:
            if size <= SIMPLE_MAX:
                meta = self._single(http, token, target, fh.read())
                on_bytes(size)
            else:
                meta = self._session(http, token, target, fh, size, on_bytes)
        if file_id is not None:
            file_id.append(str(meta.get("id") or ""))
        return int(meta.get("size") or 0)

    def _single(self, http: httpx.Client, token: str, target: str, data: bytes) -> dict[str, Any]:
        for drops in range(4):
            try:
                r = http.put(
                    f"{target}/content",
                    params={"@microsoft.graph.conflictBehavior": "rename"},
                    content=data,
                    headers=_auth(token) | {"Content-Type": "application/octet-stream"},
                )
                return dict(_check(r).json())
            except httpx.HTTPError:
                if drops == 3:
                    raise CloudError("unreachable", "The connection to OneDrive kept dropping.") from None
        raise AssertionError("unreachable")  # pragma: no cover

    def _session(
        self,
        http: httpx.Client,
        token: str,
        target: str,
        fh: Any,
        size: int,
        on_bytes: Callable[[int], None],
    ) -> dict[str, Any]:
        body = {"item": {"@microsoft.graph.conflictBehavior": "rename"}}
        r = http.post(f"{target}/createUploadSession", json=body, headers=_auth(token))
        url = str(_check(r).json()["uploadUrl"])
        offset = 0
        drops = 0
        while True:
            fh.seek(offset)
            piece = fh.read(CHUNK)
            headers = {
                "Content-Length": str(len(piece)),
                "Content-Range": f"bytes {offset}-{offset + len(piece) - 1}/{size}",
            }
            try:
                r = http.put(url, content=piece, headers=headers)  # the upload URL carries its own authorisation
            except httpx.HTTPError:
                drops += 1
                if drops > 3:
                    raise CloudError("unreachable", "The connection to OneDrive kept dropping.") from None
                new_offset = self._next(http, url)
                on_bytes(new_offset - offset)
                offset = new_offset
                continue
            if r.status_code in (200, 201):
                on_bytes(size - offset)
                return dict(r.json())
            if r.status_code == 202:
                new_offset = _first_missing(r.json(), offset + len(piece))
                on_bytes(new_offset - offset)
                offset = new_offset
                continue
            if r.status_code == 416:  # a range OneDrive has already: ask where to go on
                new_offset = self._next(http, url)
                on_bytes(new_offset - offset)
                offset = new_offset
                continue
            _check(r)
            raise CloudError("unreachable", "OneDrive did not take the file. RecallSpring tries again later.")

    def _next(self, http: httpx.Client, url: str) -> int:
        try:
            r = http.get(url)
        except httpx.HTTPError as exc:
            raise CloudError("unreachable", "The connection to OneDrive kept dropping.") from exc
        return _first_missing(_check(r).json(), 0)


def _first_missing(body: dict[str, Any], default: int) -> int:
    """The start of the first range OneDrive still expects ("26214400-" or "26214400-30000000")."""
    ranges = body.get("nextExpectedRanges") or []
    try:
        return int(str(ranges[0]).split("-", 1)[0])
    except (IndexError, ValueError):
        return default
