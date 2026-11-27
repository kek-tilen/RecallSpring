"""Cloud copy of the encrypted backups (docs/08 -> Backups -> Cloud copy, decided 2026-11-27). Google Drive first.

RecallSpring uploads its own encrypted backups to a folder it creates in the learner's Google Drive, with no sync app.
The local backup folder stays the main copy; the cloud copy follows it after every backup and removes what the local
folder removed, so the cloud keeps the same backups (7 daily and 4 weekly, or the last 7).

- Sign-in: OAuth device authorization ("TVs and Limited Input devices"): Google shows a short code the learner types
  at google.com/device on any device; no return address is needed. Scope ``drive.file`` only: RecallSpring sees only
  the files it created. The app ID and its (installed-app, not confidential) secret come from the server settings
  (RS_CLOUD_GOOGLE_CLIENT_ID / RS_CLOUD_GOOGLE_CLIENT_SECRET), never from Git (2026-11-27).
- Only the refresh token is kept, protected like the ChatGPT sign-in (``secrets_dir``: DPAPI on Windows, 0600
  elsewhere); never in the database, a backup, History, logs or the browser. No account details are stored.
- Only encrypted backups leave the computer: a snapshot whose manifest is not encrypted is never uploaded, and
  connecting needs encryption on.
- The layout in Drive is the backup folder's own (``snapshots/<name>/…`` and ``sealed/…``), so a folder downloaded
  from drive.google.com restores with ``recallspring backup-restore --from <folder> --key <recovery key file>``.
- No model calls; plain scheduled work. Failures never affect the local backup; retries wait longer each time.
- Audited: backup.cloud_connected, backup.cloud_disconnected, backup.cloud_failed (once per run of failures),
  backup.cloud_files_deleted.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from . import backup, clock
from .ai import siwc_store as store
from .config import get_settings

log = logging.getLogger(__name__)

PROVIDERS = ("google",)
GOOGLE_DEVICE = "https://oauth2.googleapis.com/device/code"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE = "https://oauth2.googleapis.com/revoke"
DRIVE = "https://www.googleapis.com/drive/v3"
DRIVE_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files"
SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER_MIME = "application/vnd.google-apps.folder"
ROOT_NAME = "RecallSpring backups"
CHUNK = 32 * 256 * 1024  # 8 MiB: Google wants multiples of 256 KiB
LOCK_ID = 727_170_002  # one copy at a time (backup.py uses ...001)
RETRY_WAITS = (timedelta(minutes=15), timedelta(hours=1), timedelta(hours=4), timedelta(hours=12))
ATTENTION_AFTER = timedelta(days=1)  # Today says so after the second day in a row, not after one failed night
SNAPSHOT_FILES = (backup.DUMP_SEALED, backup.SECRET_MANIFEST, "manifest.json")  # manifest last: complete when present

# Tests replace these: the HTTP transport (a fake Google) and how a background copy starts.
_transport: httpx.BaseTransport | None = None
_spawn: Callable[[Callable[[], Any]], None] = lambda f: threading.Thread(target=f, daemon=True).start()  # noqa: E731


class CloudError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------- state


def _token_path() -> Path:
    return store._dir() / "cloud-google.bin"


def _pending_path() -> Path:
    return store._dir() / "cloud-google-pending.bin"


def _read_secret(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(store._open(path.read_bytes()))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_secret(path: Path, data: dict[str, Any]) -> None:
    store._write_atomic(path, store._seal(json.dumps(data).encode("utf-8")))


def _status_path() -> Path:
    return get_settings().run_dir / "cloud-status.json"


def read_status() -> dict[str, Any]:
    try:
        data = json.loads(_status_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _update_status(**changes: Any) -> dict[str, Any]:
    st = read_status() | changes
    backup._write_json(_status_path(), st)
    return st


def connection() -> dict[str, Any] | None:
    """{"provider", "folder_id", "connected_at"} while connected (the folder id is not a secret)."""
    value = backup.read_config().get("cloud")
    if isinstance(value, dict) and value.get("provider") in PROVIDERS and _token_path().exists():
        return value
    return None


def _save_connection(value: dict[str, Any] | None) -> None:
    config = backup.read_config()
    if value is None:
        config.pop("cloud", None)
    else:
        config["cloud"] = value
    backup._write_json(get_settings().backup_settings_file, config)


def configured() -> bool:
    s = get_settings()
    return bool(s.cloud_google_client_id and s.cloud_google_client_secret)


def _client() -> tuple[str, str]:
    s = get_settings()
    if not configured():
        raise CloudError(
            "not_configured",
            "Google Drive needs an app ID in the server settings (RS_CLOUD_GOOGLE_CLIENT_ID and "
            "RS_CLOUD_GOOGLE_CLIENT_SECRET); docs/08 → Cloud copy.",
        )
    return (
        s.cloud_google_client_id or "",
        s.cloud_google_client_secret.get_secret_value() if s.cloud_google_client_secret else "",
    )


def _http() -> httpx.Client:
    return httpx.Client(transport=_transport, timeout=httpx.Timeout(60.0, connect=15.0))


# ---------------------------------------------------------------- sign-in (device authorization)


def start_google() -> dict[str, Any]:
    """Ask Google for a code the learner types at google.com/device. The device code stays on the server."""
    if backup.encryption() is None:
        raise CloudError("needs_encryption", "Turn on encryption first: only encrypted backups leave this computer.")
    client_id, _ = _client()
    try:
        with _http() as http:
            r = http.post(GOOGLE_DEVICE, data={"client_id": client_id, "scope": SCOPE})
    except httpx.HTTPError as exc:
        raise CloudError("unreachable", "Could not reach Google. Check the connection and try again.") from exc
    if r.status_code != 200:
        raise CloudError("refused", "Google did not give a sign-in code. Check the app ID in the server settings.")
    body = r.json()
    now = clock.now()
    pending = {
        "device_code": body["device_code"],
        "user_code": body["user_code"],
        "verification_url": body.get("verification_url")
        or body.get("verification_uri")
        or "https://www.google.com/device",
        "expires_at": (now + timedelta(seconds=int(body.get("expires_in", 1800)))).isoformat(),
        "interval": max(5, int(body.get("interval", 5))),
        "next_poll_at": now.isoformat(),
    }
    _write_secret(_pending_path(), pending)
    return _pending_view(pending)


def _pending_view(p: dict[str, Any]) -> dict[str, Any]:
    return {k: p[k] for k in ("user_code", "verification_url", "expires_at", "interval")}


def pending() -> dict[str, Any] | None:
    p = _read_secret(_pending_path())
    if p is None or (backup._parse(p.get("expires_at")) or clock.now()) <= clock.now():
        return None
    return _pending_view(p)


def cancel() -> None:
    _pending_path().unlink(missing_ok=True)


def poll_google(*, actor_id: uuid.UUID | None = None, request_id: str | None = None) -> str:
    """One check whether the learner finished signing in: pending, connected, denied or expired."""
    p = _read_secret(_pending_path())
    if p is None:
        return "expired"
    now = clock.now()
    if (backup._parse(p.get("expires_at")) or now) <= now:
        cancel()
        return "expired"
    if (backup._parse(p.get("next_poll_at")) or now) > now:
        return "pending"  # Google asks for at least `interval` seconds between checks
    client_id, secret = _client()
    data = {
        "client_id": client_id,
        "client_secret": secret,
        "device_code": p["device_code"],
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    try:
        with _http() as http:
            r = http.post(GOOGLE_TOKEN, data=data)
    except httpx.HTTPError:
        return "pending"
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code == 200 and body.get("refresh_token"):
        cancel()
        _write_secret(_token_path(), {"refresh_token": body["refresh_token"], "scope": body.get("scope", SCOPE)})
        try:
            with _http() as http:
                folder = _ensure_folder(http, body["access_token"], ROOT_NAME, None)
        except CloudError:
            _token_path().unlink(missing_ok=True)
            raise
        _save_connection({"provider": "google", "folder_id": folder, "connected_at": now.isoformat()})
        backup._write_json(_status_path(), {"state": "waiting"})
        backup._audit(actor_id, "backup.cloud_connected", {"provider": "google"}, request_id)
        return "connected"
    error = body.get("error")
    if error == "slow_down":
        p["interval"] = int(p["interval"]) + 5
    if error in ("authorization_pending", "slow_down"):
        p["next_poll_at"] = (now + timedelta(seconds=int(p["interval"]))).isoformat()
        _write_secret(_pending_path(), p)
        return "pending"
    cancel()
    return "denied" if error == "access_denied" else "expired"


def _access_token(http: httpx.Client) -> str:
    token = _read_secret(_token_path())
    if not token:
        raise CloudError("revoked", "Google Drive is not connected any more. Connect it again in Settings.")
    client_id, secret = _client()
    data = {
        "client_id": client_id,
        "client_secret": secret,
        "refresh_token": token["refresh_token"],
        "grant_type": "refresh_token",
    }
    try:
        r = http.post(GOOGLE_TOKEN, data=data)
    except httpx.HTTPError as exc:
        raise CloudError("unreachable", "Could not reach Google Drive. RecallSpring tries again later.") from exc
    try:
        error = r.json().get("error") if r.status_code >= 400 else None
    except ValueError:
        error = None
    if r.status_code in (400, 401) and error in ("invalid_grant", "unauthorized_client"):
        raise CloudError("revoked", REVOKED)
    if r.status_code != 200:
        raise CloudError("unreachable", "Google Drive did not answer as expected. RecallSpring tries again later.")
    return str(r.json()["access_token"])


# ---------------------------------------------------------------- Drive


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


REVOKED = "Google Drive no longer allows RecallSpring. Your backups are still made on this computer."


def _check(r: httpx.Response) -> httpx.Response:
    if r.status_code < 400:
        return r
    if r.status_code == 403 and "storageQuotaExceeded" in r.text:
        raise CloudError("no_room", "Not enough room in your Google Drive. RecallSpring tries again tomorrow.")
    if r.status_code == 401 or (r.status_code == 403 and "ateLimitExceeded" not in r.text):
        raise CloudError("revoked", REVOKED)
    if r.status_code == 404:
        raise CloudError("missing", "A folder RecallSpring made in Google Drive is gone. RecallSpring makes it again.")
    raise CloudError("unreachable", "Google Drive did not answer as expected. RecallSpring tries again later.")


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _children(http: httpx.Client, token: str, parent: str) -> dict[str, dict[str, Any]]:
    """name -> {id, size, folder} of what is directly in a folder (only what RecallSpring made: drive.file)."""
    found: dict[str, dict[str, Any]] = {}
    params: dict[str, Any] = {
        "q": f"'{_quote(parent)}' in parents and trashed=false",
        "fields": "nextPageToken,files(id,name,size,mimeType)",
        "pageSize": 1000,
        "spaces": "drive",
    }
    while True:
        body = _check(http.get(f"{DRIVE}/files", params=params, headers=_auth(token))).json()
        for f in body.get("files", []):
            found[f["name"]] = {
                "id": f["id"],
                "size": int(f.get("size") or 0),
                "folder": f.get("mimeType") == FOLDER_MIME,
            }
        if not body.get("nextPageToken"):
            return found
        params["pageToken"] = body["nextPageToken"]


def _ensure_folder(http: httpx.Client, token: str, name: str, parent: str | None) -> str:
    q = f"name='{_quote(name)}' and mimeType='{FOLDER_MIME}' and trashed=false"
    q += f" and '{_quote(parent)}' in parents" if parent else " and 'root' in parents"
    body = _check(http.get(f"{DRIVE}/files", params={"q": q, "fields": "files(id)"}, headers=_auth(token))).json()
    if body.get("files"):
        return str(body["files"][0]["id"])
    meta: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME}
    if parent:
        meta["parents"] = [parent]
    return str(
        _check(http.post(f"{DRIVE}/files", json=meta, params={"fields": "id"}, headers=_auth(token))).json()["id"]
    )


def _upload(http: httpx.Client, token: str, path: Path, parent: str, on_bytes: Callable[[int], None]) -> int:
    """Resumable upload in 8 MiB pieces; a dropped piece asks Google how far it got and continues. Returns the size
    Google reports."""
    size = path.stat().st_size
    start = http.post(
        DRIVE_UPLOAD,
        params={"uploadType": "resumable", "fields": "id,size"},
        json={"name": path.name, "parents": [parent]},
        headers=_auth(token)
        | {"X-Upload-Content-Type": "application/octet-stream", "X-Upload-Content-Length": str(size)},
    )
    session = _check(start).headers["location"]
    offset = 0
    drops = 0
    ask = False  # after a dropped piece: ask Google how far it got
    with path.open("rb") as fh:
        while True:
            fh.seek(offset)
            piece = b"" if ask else fh.read(CHUNK)
            headers = {
                "Content-Range": f"bytes {offset}-{offset + len(piece) - 1}/{size}" if piece else f"bytes */{size}"
            }
            try:
                r = http.put(session, content=piece, headers=_auth(token) | headers)
            except httpx.HTTPError:
                drops += 1
                if drops > 3:
                    raise CloudError("unreachable", "The connection to Google Drive kept dropping.") from None
                ask = True
                continue
            ask = False
            if r.status_code in (200, 201):
                on_bytes(size - offset)
                return int(r.json().get("size") or size)
            if r.status_code != 308:
                _check(r)
                raise CloudError("unreachable", "Google Drive did not take the file. RecallSpring tries again later.")
            got = r.headers.get("range")  # "bytes=0-8388607"
            new_offset = int(got.rsplit("-", 1)[1]) + 1 if got else 0
            on_bytes(new_offset - offset)
            offset = new_offset


def _delete(http: httpx.Client, token: str, file_id: str) -> None:
    r = http.delete(f"{DRIVE}/files/{file_id}", headers=_auth(token))
    if r.status_code not in (204, 200, 404):
        _check(r)


def _free_bytes(http: httpx.Client, token: str) -> int | None:
    quota = _check(http.get(f"{DRIVE}/about", params={"fields": "storageQuota"}, headers=_auth(token))).json()
    q = quota.get("storageQuota", {})
    if "limit" not in q:
        return None  # no limit stated
    return max(0, int(q["limit"]) - int(q.get("usage", 0)))


# ---------------------------------------------------------------- copy


@contextmanager
def _locked() -> Iterator[None]:
    engine = create_engine(backup._db_url(), pool_pre_ping=True)
    try:
        try:
            conn = engine.connect()
        except SQLAlchemyError as exc:
            raise CloudError("busy", "Could not connect to the database.") from exc
        with conn:
            got = conn.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}).scalar_one()
            conn.commit()
            if not got:
                raise CloudError("busy", "A copy is running right now.")
            try:
                yield
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
                conn.commit()
    finally:
        engine.dispose()


def _local() -> tuple[list[Path], dict[str, Path]]:
    """Encrypted snapshots (oldest first) and the sealed files they need, by name."""
    root = backup.backup_root()
    snaps = [p for p in backup.snapshots() if backup._manifest(p).get("encrypted")]
    sealed: dict[str, Path] = {}
    for p in snaps:
        for name in backup._manifest(p).get("files", {}).get("sealed", []):
            f = root / "sealed" / name
            if backup.SEALED_RE.match(name) and f.is_file():
                sealed[name] = f
    return snaps, sealed


def _human(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.1f} GB"
    return f"{round(n / 1024**2)} MB" if n >= 1024**2 else f"{round(n / 1024)} KB"


def copy(
    reason: str = "scheduled", *, actor_id: uuid.UUID | None = None, request_id: str | None = None
) -> dict[str, Any]:
    """Copy what is new, confirm the sizes, then remove what the local folder removed. Never raises CloudError to
    the worker: the failure is recorded and retried later."""
    conn = connection()
    if conn is None:
        return read_status()
    started = clock.now()
    try:
        with _locked():
            return _copy_locked(conn, started, reason)
    except CloudError as exc:
        if exc.code == "busy":
            return read_status()
        return _record_failure(exc, started, actor_id, request_id)
    except Exception as exc:  # noqa: BLE001 - recorded without details that could hold secrets
        log.exception("cloud copy failed unexpectedly")
        error = CloudError("unexpected", f"Unexpected error: {type(exc).__name__}. RecallSpring tries again later.")
        return _record_failure(error, started, actor_id, request_id)


def _copy_locked(conn: dict[str, Any], started: datetime, reason: str) -> dict[str, Any]:
    snaps, sealed = _local()
    _update_status(state="copying", last_attempt_at=started.isoformat(), progress=None)
    with _http() as http:
        token = _access_token(http)
        root = conn["folder_id"]
        try:
            top = _children(http, token, root)
        except CloudError as exc:
            if exc.code != "missing":
                raise
            root = _ensure_folder(http, token, ROOT_NAME, None)
            _save_connection(conn | {"folder_id": root})
            top = {}
        snap_folder = top["snapshots"]["id"] if "snapshots" in top else _ensure_folder(http, token, "snapshots", root)
        sealed_folder = top["sealed"]["id"] if "sealed" in top else _ensure_folder(http, token, "sealed", root)
        remote_sealed = _children(http, token, sealed_folder)
        remote_snaps = _children(http, token, snap_folder)
        # What is missing: sealed files first, then each snapshot with its manifest last.
        todo: list[tuple[Path, str | None, str]] = []  # (file, parent id or None = the snapshot's folder, snapshot)
        for name, f in sealed.items():
            if remote_sealed.get(name, {}).get("size") != f.stat().st_size:
                todo.append((f, sealed_folder, ""))
        per_snap: dict[str, dict[str, dict[str, Any]]] = {}
        for p in snaps:
            have = _children(http, token, remote_snaps[p.name]["id"]) if p.name in remote_snaps else {}
            per_snap[p.name] = have
            for n in SNAPSHOT_FILES:
                f = p / n
                if f.is_file() and have.get(n, {}).get("size") != f.stat().st_size:
                    todo.append((f, None, p.name))
        need = sum(f.stat().st_size for f, _, _ in todo)
        free = _free_bytes(http, token)
        if free is not None and need > free:
            raise CloudError(
                "no_room",
                f"Not enough room in your Google Drive for the new backup (needs {_human(need)}, {_human(free)} "
                "free). RecallSpring tries again tomorrow.",
            )
        done = {"files": 0, "bytes": 0}
        total = {"files": len(todo), "bytes": need}

        def progress(n: int) -> None:
            done["bytes"] += n
            _update_status(
                progress={
                    "done_files": done["files"],
                    "total_files": total["files"],
                    "done_bytes": done["bytes"],
                    "total_bytes": total["bytes"],
                }
            )

        folders: dict[str, str] = {name: v["id"] for name, v in remote_snaps.items()}
        for f, parent, snap in todo:
            if parent is None:
                if snap not in folders:
                    folders[snap] = _ensure_folder(http, token, snap, snap_folder)
                parent = folders[snap]
                stale = per_snap.get(snap, {}).get(f.name)
            else:
                stale = remote_sealed.get(f.name)
            if stale:  # a partial or different file from an earlier try
                _delete(http, token, stale["id"])
            got = _upload(http, token, f, parent, progress)
            if got != f.stat().st_size:
                raise CloudError(
                    "mismatch", "A file in Google Drive does not match its backup. RecallSpring tries again later."
                )
            done["files"] += 1
        # Tidy: the cloud keeps what the local folder keeps. Only RecallSpring's own files are visible (drive.file).
        local_names = {p.name for p in snaps}
        for name, v in remote_snaps.items():
            if name not in local_names and backup.SNAPSHOT_RE.match(name):
                _delete(http, token, v["id"])
        for name, v in remote_sealed.items():
            if name not in sealed and backup.SEALED_RE.match(name):
                _delete(http, token, v["id"])
        free = _free_bytes(http, token)
    copied_bytes = sum(f.stat().st_size for f in sealed.values()) + sum(
        (p / n).stat().st_size for p in snaps for n in SNAPSHOT_FILES if (p / n).is_file()
    )
    now = clock.now()
    st = read_status()
    st.update(
        state="ok",
        last_success_at=now.isoformat(),
        last_attempt_at=started.isoformat(),
        last_snapshot=snaps[-1].name if snaps else None,
        backups=len(snaps),
        bytes=copied_bytes,
        free_bytes=free,
        progress=None,
        error=None,
        failures=0,
        failing_since=None,
        next_try_at=None,
        reason=reason,
    )
    backup._write_json(_status_path(), st)
    log.info("cloud copy done: %s backups, %s new files", len(snaps), total["files"])
    return st


def _record_failure(
    exc: CloudError, started: datetime, actor_id: uuid.UUID | None, request_id: str | None
) -> dict[str, Any]:
    st = read_status()
    first = not st.get("failing_since")
    failures = int(st.get("failures") or 0) + 1
    wait = RETRY_WAITS[min(failures, len(RETRY_WAITS)) - 1]
    if exc.code == "no_room":
        wait = max(wait, timedelta(hours=20))  # "tries again tomorrow"
    st.update(
        state="revoked" if exc.code == "revoked" else "failing",
        last_attempt_at=started.isoformat(),
        error={"code": exc.code, "message": exc.message, "at": clock.now().isoformat()},
        failures=failures,
        failing_since=st.get("failing_since") or started.isoformat(),
        next_try_at=None if exc.code == "revoked" else (clock.now() + wait).isoformat(),
        progress=None,
    )
    backup._write_json(_status_path(), st)
    if first:
        backup._audit(actor_id, "backup.cloud_failed", {"provider": "google", "code": exc.code}, request_id)
    log.warning("cloud copy failed (%s)", exc.code)
    return st


def due() -> bool:
    """Connected, something new to copy (or a tidy owed), and not waiting before a retry."""
    if connection() is None:
        return False
    st = read_status()
    if st.get("state") == "revoked":
        return False
    nxt = backup._parse(st.get("next_try_at"))
    if nxt is not None and clock.now() < nxt:
        return False
    snaps, _ = _local()
    newest = snaps[-1].name if snaps else None
    return st.get("state") != "ok" or st.get("last_snapshot") != newest or st.get("backups") != len(snaps)


def copy_if_due() -> bool:
    """Called by the worker after its backup check. Never raises."""
    if not due():
        return False
    try:
        copy("scheduled")
    except Exception:  # noqa: BLE001 - the worker must keep processing jobs
        log.exception("scheduled cloud copy crashed")
    return True


def copy_in_background(*, actor_id: uuid.UUID | None = None, request_id: str | None = None) -> None:
    """Copy now (Settings), without holding the request: the page follows the status."""
    _update_status(state="copying", next_try_at=None, progress=None)
    _spawn(lambda: copy("manual", actor_id=actor_id, request_id=request_id))


# ---------------------------------------------------------------- disconnect


def disconnect(delete_files: bool, *, actor_id: uuid.UUID | None = None, request_id: str | None = None) -> None:
    """Forget the sign-in and ask Google to withdraw it. The files in Drive stay unless delete_files (the page asked
    once more); deleting removes only the folder RecallSpring made."""
    conn = connection()
    token = _read_secret(_token_path())
    deleted = False
    if conn is not None and token:
        with _http() as http:
            if delete_files:
                access = _access_token(http)
                _delete(http, access, conn["folder_id"])
                deleted = True
            try:
                http.post(GOOGLE_REVOKE, data={"token": token["refresh_token"]})
            except httpx.HTTPError:
                log.warning("could not ask Google to withdraw the sign-in; it is forgotten here")
    _token_path().unlink(missing_ok=True)
    cancel()
    _save_connection(None)
    _status_path().unlink(missing_ok=True)
    if deleted:
        backup._audit(actor_id, "backup.cloud_files_deleted", {"provider": "google"}, request_id)
    backup._audit(
        actor_id,
        "backup.cloud_disconnected",
        {"provider": "google", "files": "deleted" if deleted else "kept"},
        request_id,
    )


# ---------------------------------------------------------------- views


def view() -> dict[str, Any]:
    """What Settings shows. No token, no device code, no account details."""
    conn = connection()
    st = read_status() if conn else {}
    return {
        "available": {"google": configured()},
        "provider": conn["provider"] if conn else None,
        "connected_at": conn.get("connected_at") if conn else None,
        "state": st.get("state", "waiting") if conn else "off",
        "last_success_at": st.get("last_success_at"),
        "backups": st.get("backups"),
        "bytes": st.get("bytes"),
        "free_bytes": st.get("free_bytes"),
        "error": st.get("error") if st.get("state") in ("failing", "revoked") else None,
        "next_try_at": st.get("next_try_at"),
        "progress": st.get("progress"),
        "pending": pending() if not conn else None,
    }


def attention_item() -> dict[str, Any] | None:
    """Today › Needs attention: at once when access was withdrawn, else after a day of failures in a row."""
    if connection() is None:
        return None
    st = read_status()
    error = st.get("error") or {}
    item: dict[str, Any] = {"kind": "cloud", "id": None, "course_id": None}
    if st.get("state") == "revoked":
        return item | {
            "title": "Cloud copy stopped",
            "text": "Google Drive no longer allows RecallSpring. Your backups are still made on this computer. "
            "Connect it again in Settings → Data & backups.",
        }
    since = backup._parse(st.get("failing_since"))
    if st.get("state") == "failing" and since is not None and clock.now() - since >= ATTENTION_AFTER:
        return item | {"title": "Cloud copy is failing", "text": str(error.get("message", "")).strip()}
    return None
