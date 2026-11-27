"""Your Google Drive (BYOS step 2, decided 2026-11-27): a readable copy of each learner's own material, by course,
in My Drive › RecallSpring, and exports sent there when the learner chooses.

Each learner signs in with their own Google account (the same device-code sign-in and Google app as the cloud copy of
backups, cloud.py; scope ``drive.file``: only files RecallSpring made). The refresh token is kept per learner in
``secrets_dir/drive-<user id>.bin`` (DPAPI on Windows, 0600 elsewhere), never in the database, a backup, History, logs
or the browser. No account name or address is stored.

Copying is one way and never blocks uploads, extraction or grading. RecallSpring keeps working from its own copy.
Material deleted in RecallSpring stays in Drive (it is the learner's copy); Disconnect can delete everything
RecallSpring made there, after asking.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .. import backup, clock, cloud
from ..ai import siwc_store as store
from ..cloud import CloudError
from ..db import new_session
from ..errors import ApiError
from ..ingest.storage import blob_path
from ..models import Course, DriveConnection, DriveItem, Export, Source, SourceFolder, User
from .events import audit
from .exports import safe_name, zip_path

log = logging.getLogger("recallspring.my_drive")

ROOT_NAME = "RecallSpring"
EXPORTS_NAME = "Exports"
LOCK_ID = 727_170_003  # one copy per learner at a time (with the learner's id as the second key)
PER_RUN = 200  # files per run; the next run continues
CHECK_SECONDS = 60  # the worker looks for new material this often

MESSAGES = {
    "revoked": "Google Drive no longer allows RecallSpring. Your material is safe here; connect again to keep copying.",
    "no_room": "Not enough room in your Google Drive. RecallSpring tries again tomorrow.",
    "unreachable": "Could not reach Google Drive. RecallSpring tries again later.",
    "missing": "A folder RecallSpring made in your Drive is gone. RecallSpring makes it again.",
    "busy": "A copy is running right now.",
}


def _error(exc: CloudError) -> CloudError:
    return CloudError(exc.code, MESSAGES.get(exc.code, exc.message))


# ---------------------------------------------------------------- secrets


def _token_path(user_id: uuid.UUID) -> Path:
    return store._dir() / f"drive-{user_id}.bin"


def _pending_path(user_id: uuid.UUID) -> Path:
    return store._dir() / f"drive-{user_id}-pending.bin"


def connection(db: Session, user_id: uuid.UUID) -> DriveConnection | None:
    row = db.get(DriveConnection, user_id)
    return row if row is not None and _token_path(user_id).exists() else None


# ---------------------------------------------------------------- sign-in (device authorization, as cloud.py)


def start(user: User) -> dict[str, Any]:
    client_id, _ = cloud._client()
    try:
        with cloud._http() as http:
            r = http.post(cloud.GOOGLE_DEVICE, data={"client_id": client_id, "scope": cloud.SCOPE})
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
    cloud._write_secret(_pending_path(user.id), pending)
    return cloud._pending_view(pending)


def pending(user_id: uuid.UUID) -> dict[str, Any] | None:
    p = cloud._read_secret(_pending_path(user_id))
    if p is None or (backup._parse(p.get("expires_at")) or clock.now()) <= clock.now():
        return None
    return cloud._pending_view(p)


def cancel(user_id: uuid.UUID) -> None:
    _pending_path(user_id).unlink(missing_ok=True)


def poll(db: Session, user: User, request_id: str | None) -> str:
    """One check whether the learner finished signing in: pending, connected, denied or expired."""
    p = cloud._read_secret(_pending_path(user.id))
    if p is None:
        return "expired"
    now = clock.now()
    if (backup._parse(p.get("expires_at")) or now) <= now:
        cancel(user.id)
        return "expired"
    if (backup._parse(p.get("next_poll_at")) or now) > now:
        return "pending"
    client_id, secret = cloud._client()
    data = {
        "client_id": client_id,
        "client_secret": secret,
        "device_code": p["device_code"],
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    try:
        with cloud._http() as http:
            r = http.post(cloud.GOOGLE_TOKEN, data=data)
    except httpx.HTTPError:
        return "pending"
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code == 200 and body.get("refresh_token"):
        cancel(user.id)
        cloud._write_secret(
            _token_path(user.id), {"refresh_token": body["refresh_token"], "scope": body.get("scope", cloud.SCOPE)}
        )
        try:
            with cloud._http() as http:
                root = cloud._ensure_folder(http, body["access_token"], ROOT_NAME, None)
        except CloudError:
            _token_path(user.id).unlink(missing_ok=True)
            raise
        old = db.get(DriveConnection, user.id)
        if old is not None:  # signing in again after access was withdrawn keeps what was copied
            old.root_id, old.state, old.error, old.failures = root, "ok", None, 0
            old.failing_since = old.next_try_at = None
        else:
            # copy_from by the database clock, as Source.uploaded_at
            db.add(DriveConnection(user_id=user.id, root_id=root, copy_from=func.now(), state="ok"))
        audit(db, actor_id=user.id, action="drive.connected", details={"provider": "google"}, request_id=request_id)
        return "connected"
    error = body.get("error")
    if error == "slow_down":
        p["interval"] = int(p["interval"]) + 5
    if error in ("authorization_pending", "slow_down"):
        p["next_poll_at"] = (now + timedelta(seconds=int(p["interval"]))).isoformat()
        cloud._write_secret(_pending_path(user.id), p)
        return "pending"
    cancel(user.id)
    return "denied" if error == "access_denied" else "expired"


# ---------------------------------------------------------------- Drive helpers


def _get(http: httpx.Client, token: str, file_id: str) -> dict[str, Any] | None:
    """The file's id, name and whether it is in the bin; None when it is gone."""
    r = http.get(f"{cloud.DRIVE}/files/{file_id}", params={"fields": "id,name,trashed"}, headers=cloud._auth(token))
    if r.status_code == 404:
        return None
    return cloud._check(r).json()


def _rename(http: httpx.Client, token: str, file_id: str, name: str) -> None:
    cloud._check(
        http.patch(
            f"{cloud.DRIVE}/files/{file_id}", json={"name": name}, params={"fields": "id"}, headers=cloud._auth(token)
        )
    )


def _new_folder(http: httpx.Client, token: str, name: str, parent: str) -> str:
    meta = {"name": name, "mimeType": cloud.FOLDER_MIME, "parents": [parent]}
    r = http.post(f"{cloud.DRIVE}/files", json=meta, params={"fields": "id"}, headers=cloud._auth(token))
    return str(cloud._check(r).json()["id"])


class _Run:
    """One copy run for one learner: folder ids are checked once per run (a folder deleted in Drive is made again)."""

    def __init__(self, db: Session, http: httpx.Client, token: str, conn: DriveConnection) -> None:
        self.db, self.http, self.token, self.conn = db, http, token, conn
        self.checked: dict[tuple[str, uuid.UUID | None], str] = {}

    def _item(self, kind: str, local_id: uuid.UUID | None) -> DriveItem | None:
        return self.db.scalar(
            select(DriveItem).where(
                DriveItem.user_id == self.conn.user_id,
                DriveItem.local_kind == kind,
                DriveItem.local_id.is_(None) if local_id is None else DriveItem.local_id == local_id,
            )
        )

    def _forget_under(self, kind: str, local_id: uuid.UUID | None) -> None:
        """A folder is gone in Drive: what was copied into it is copied again on the next run."""
        if kind == "course":
            folders = set(self.db.scalars(select(SourceFolder.id).where(SourceFolder.course_id == local_id)))
            sources = set(self.db.scalars(select(Source.id).where(Source.course_id == local_id)))
        elif kind == "source_folder":
            folders, frontier = {local_id}, {local_id}
            while frontier:
                frontier = set(self.db.scalars(select(SourceFolder.id).where(SourceFolder.parent_id.in_(frontier))))
                frontier -= folders
                folders |= frontier
            sources = set(self.db.scalars(select(Source.id).where(Source.folder_id.in_(folders))))
        else:
            sources, folders = set(), set()
            if kind == "exports":
                ids = select(DriveItem.id).where(
                    DriveItem.user_id == self.conn.user_id, DriveItem.local_kind == "export"
                )
                for gone in self.db.scalars(select(DriveItem).where(DriveItem.id.in_(ids))):
                    self.db.delete(gone)
            return
        for gone in self.db.scalars(
            select(DriveItem).where(
                DriveItem.user_id == self.conn.user_id,
                ((DriveItem.local_kind == "source") & DriveItem.local_id.in_(sources))
                | ((DriveItem.local_kind == "source_folder") & DriveItem.local_id.in_(folders - {local_id})),
            )
        ):
            self.db.delete(gone)

    def root(self) -> str:
        if ("root", None) not in self.checked:
            found = _get(self.http, self.token, self.conn.root_id)
            if found is None or found.get("trashed"):
                # The whole folder is gone: make it again and copy everything again.
                self.conn.root_id = cloud._ensure_folder(self.http, self.token, ROOT_NAME, None)
                for item in self.db.scalars(select(DriveItem).where(DriveItem.user_id == self.conn.user_id)):
                    self.db.delete(item)
                self.db.flush()
            self.checked[("root", None)] = self.conn.root_id
        return self.checked[("root", None)]

    def folder(self, kind: str, local_id: uuid.UUID | None, name: str, parent: str) -> str:
        key = (kind, local_id)
        if key in self.checked:
            return self.checked[key]
        item = self._item(kind, local_id)
        if item is not None:
            found = _get(self.http, self.token, item.drive_id)
            if found is None or found.get("trashed"):
                self.db.delete(item)
                self._forget_under(kind, local_id)
                self.db.flush()
                item = None
            elif item.name != name:  # renamed in RecallSpring: rename in Drive too
                _rename(self.http, self.token, item.drive_id, name)
                item.name = name
        if item is None:
            item = DriveItem(
                user_id=self.conn.user_id,
                local_kind=kind,
                local_id=local_id,
                drive_id=_new_folder(self.http, self.token, name, parent),
                name=name,
            )
            self.db.add(item)
            self.db.flush()
        self.checked[key] = item.drive_id
        return item.drive_id

    def course(self, course: Course) -> str:
        return self.folder("course", course.id, safe_name(course.title, "course"), self.root())

    def source_folder(self, course: Course, folder_id: uuid.UUID | None) -> str:
        if folder_id is None:
            return self.course(course)
        chain: list[SourceFolder] = []
        cur = self.db.get(SourceFolder, folder_id)
        while cur is not None and cur.deleted_at is None and cur not in chain:
            chain.append(cur)
            cur = self.db.get(SourceFolder, cur.parent_id) if cur.parent_id else None
        parent = self.course(course)
        for f in reversed(chain):
            parent = self.folder("source_folder", f.id, safe_name(f.name, "folder"), parent)
        return parent

    def upload(self, path: Path, parent: str, name: str, kind: str, local_id: uuid.UUID, on_bytes: Any) -> None:
        ids: list[str] = []
        size = cloud._upload(self.http, self.token, path, parent, on_bytes, name=name, file_id=ids)
        self.db.add(
            DriveItem(
                user_id=self.conn.user_id,
                local_kind=kind,
                local_id=local_id,
                drive_id=ids[0] if ids else "",
                name=name,
                byte_size=size,
            )
        )
        self.db.flush()


@contextmanager
def _locked(user_id: uuid.UUID) -> Iterator[None]:
    engine = create_engine(backup._db_url(), pool_pre_ping=True)
    try:
        try:
            conn = engine.connect()
        except SQLAlchemyError as exc:
            raise CloudError("busy", MESSAGES["busy"]) from exc
        with conn:
            key = {"a": LOCK_ID, "b": int.from_bytes(user_id.bytes[:4], "big", signed=True)}
            got = conn.execute(text("SELECT pg_try_advisory_lock(:a, :b)"), key).scalar_one()
            conn.commit()
            if not got:
                raise CloudError("busy", MESSAGES["busy"])
            try:
                yield
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:a, :b)"), key)
                conn.commit()
    finally:
        engine.dispose()


# ---------------------------------------------------------------- copying


def _waiting(db: Session, conn: DriveConnection, limit: int | None = None) -> list[Source]:
    copied = select(DriveItem.local_id).where(DriveItem.user_id == conn.user_id, DriveItem.local_kind == "source")
    query = (
        select(Source)
        .join(Course, Course.id == Source.course_id)
        .where(
            Source.user_id == conn.user_id,
            Source.deleted_at.is_(None),
            Course.deleted_at.is_(None),
            Source.id.not_in(copied),
        )
        .order_by(Source.uploaded_at)
    )
    if conn.copy_from is not None:
        query = query.where(Source.uploaded_at >= conn.copy_from)
    if limit:
        query = query.limit(limit)
    return list(db.scalars(query))


def _not_yet(db: Session, conn: DriveConnection) -> tuple[int, int]:
    """Material from before the connection that is not copied (offered as "Copy what is already here")."""
    if conn.copy_from is None:
        return 0, 0
    copied = select(DriveItem.local_id).where(DriveItem.user_id == conn.user_id, DriveItem.local_kind == "source")
    n, size = db.execute(
        select(func.count(), func.coalesce(func.sum(Source.byte_size), 0))
        .join(Course, Course.id == Source.course_id)
        .where(
            Source.user_id == conn.user_id,
            Source.deleted_at.is_(None),
            Course.deleted_at.is_(None),
            Source.uploaded_at < conn.copy_from,
            Source.id.not_in(copied),
        )
    ).one()
    return int(n), int(size)


def sync(user_id: uuid.UUID) -> str:
    """Copy waiting material for one learner. Returns ok, nothing, failing, revoked or busy. Never raises."""
    try:
        with _locked(user_id):
            return _sync(user_id)
    except CloudError as exc:
        return "busy" if exc.code == "busy" else _failed(user_id, _error(exc))
    except Exception:  # noqa: BLE001 - the worker must keep running
        log.exception("drive copy crashed")
        return _failed(user_id, CloudError("unreachable", MESSAGES["unreachable"]))


def _sync(user_id: uuid.UUID) -> str:
    with new_session() as db:
        conn = connection(db, user_id)
        if conn is None or conn.state == "revoked" or not conn.mirror:
            return "nothing"
        todo = _waiting(db, conn, PER_RUN)
        if not todo:
            if conn.state != "ok":
                conn.state, conn.progress = "ok", None
                db.commit()
            return "nothing"
        total_bytes = sum(s.byte_size for s in todo)
        conn.state, conn.progress = (
            "copying",
            {"done_files": 0, "total_files": len(todo), "done_bytes": 0, "total_bytes": total_bytes},
        )
        db.commit()
        done = {"bytes": 0}
        with cloud._http() as http:
            token = cloud._access_token(http, _token_path(user_id))
            run = _Run(db, http, token, conn)
            free = cloud._free_bytes(http, token)
            if free is not None and free < total_bytes:
                raise CloudError("no_room", MESSAGES["no_room"])
            for i, source in enumerate(todo):
                course = db.get(Course, source.course_id)
                path = blob_path(source.storage_key)
                if course is None or not path.exists():
                    continue
                parent = run.source_folder(course, source.folder_id)

                def moved(n: int) -> None:
                    done["bytes"] += n

                run.upload(path, parent, safe_name(source.filename, "document", 160), "source", source.id, moved)
                conn.progress = {
                    "done_files": i + 1,
                    "total_files": len(todo),
                    "done_bytes": done["bytes"],
                    "total_bytes": total_bytes,
                }
                db.commit()
            conn.free_bytes = cloud._free_bytes(http, token)
        conn.state, conn.progress, conn.error = "ok", None, None
        conn.failures, conn.failing_since, conn.next_try_at = 0, None, None
        conn.last_success_at = clock.now()
        db.commit()
    log.info("drive copy for a learner: %s files", len(todo))
    return "ok"


def _failed(user_id: uuid.UUID, exc: CloudError) -> str:
    with new_session() as db:
        conn = db.get(DriveConnection, user_id)
        if conn is None:
            return "nothing"
        first = conn.failing_since is None
        conn.failures += 1
        wait = cloud.RETRY_WAITS[min(conn.failures, len(cloud.RETRY_WAITS)) - 1]
        if exc.code == "no_room":
            wait = max(wait, timedelta(hours=20))
        now = clock.now()
        conn.state = "revoked" if exc.code == "revoked" else "failing"
        conn.error = {"code": exc.code, "message": exc.message, "at": now.isoformat()}
        conn.failing_since = conn.failing_since or now
        conn.next_try_at = None if exc.code == "revoked" else now + wait
        conn.progress = None
        if first:
            audit(db, actor_id=user_id, action="drive.failed", details={"provider": "google", "code": exc.code})
        db.commit()
    log.warning("drive copy failed (%s)", exc.code)
    return conn.state


def due_users(now: datetime | None = None) -> list[uuid.UUID]:
    now = now or clock.now()
    with new_session() as db:
        rows = db.scalars(
            select(DriveConnection).where(
                DriveConnection.mirror.is_(True),
                DriveConnection.state != "revoked",
                (DriveConnection.next_try_at.is_(None)) | (DriveConnection.next_try_at <= now),
            )
        )
        return [r.user_id for r in rows if _waiting(db, r, 1) or r.state == "copying"]


def sync_all() -> int:
    """Called by the worker every minute. Never raises."""
    n = 0
    try:
        for user_id in due_users():
            if sync(user_id) == "ok":
                n += 1
    except Exception:  # noqa: BLE001
        log.exception("drive copy check failed")
    return n


def sync_in_background(user_id: uuid.UUID) -> None:
    cloud._spawn(lambda: sync(user_id))


# ---------------------------------------------------------------- exports


def send_export(export_id: uuid.UUID) -> str | None:
    """Upload a finished export to My Drive › RecallSpring › Exports. Returns None, or an error code."""
    user_id: uuid.UUID | None = None
    try:
        with new_session() as db:
            row = db.get(Export, export_id)
            if row is None or row.state != "ready":
                return "export_gone"
            user_id = row.user_id
            conn = connection(db, row.user_id)
            if conn is None or conn.state == "revoked":
                return "revoked"
            with _locked(row.user_id), cloud._http() as http:
                token = cloud._access_token(http, _token_path(row.user_id))
                run = _Run(db, http, token, conn)
                folder = run.folder("exports", None, EXPORTS_NAME, run.root())
                name = f"RecallSpring export {row.created_at:%Y-%m-%d %H%M}.zip"
                run.upload(zip_path(row), folder, name, "export", row.id, lambda n: None)
            audit(
                db,
                actor_id=row.user_id,
                action="export.sent_to_drive",
                target_type="export",
                target_id=row.id,
                details={"bytes": row.byte_size},
            )
            db.commit()
        return None
    except CloudError as exc:
        log.warning("export to drive failed (%s)", exc.code)
        if exc.code == "revoked" and user_id is not None:
            _failed(user_id, _error(exc))  # the Drive row and Today say so too
        return exc.code
    except Exception:  # noqa: BLE001
        log.exception("export to drive crashed")
        return "unreachable"


# ---------------------------------------------------------------- settings


def set_options(db: Session, user: User, *, mirror: bool | None, exports: bool | None) -> DriveConnection:
    conn = connection(db, user.id)
    if conn is None:
        raise ApiError(409, "drive_not_connected", "Connect your Google Drive first.")
    if mirror is not None:
        conn.mirror = mirror
    if exports is not None:
        conn.exports = exports
    return conn


def copy_existing(db: Session, user: User, request_id: str | None) -> tuple[int, int]:
    conn = connection(db, user.id)
    if conn is None:
        raise ApiError(409, "drive_not_connected", "Connect your Google Drive first.")
    n, size = _not_yet(db, conn)
    conn.copy_from, conn.mirror, conn.next_try_at = None, True, None
    audit(
        db, actor_id=user.id, action="drive.copy_existing", details={"files": n, "bytes": size}, request_id=request_id
    )
    return n, size


def disconnect(db: Session, user: User, delete_files: bool, request_id: str | None) -> None:
    """Forget the sign-in and ask Google to withdraw it; the files stay unless ``delete_files`` (asked once more)."""
    conn = db.get(DriveConnection, user.id)
    token = cloud._read_secret(_token_path(user.id))
    deleted = False
    if conn is not None and token:
        try:
            with cloud._http() as http:
                if delete_files:
                    access = cloud._access_token(http, _token_path(user.id))
                    cloud._delete(http, access, conn.root_id)
                    deleted = True
                try:
                    http.post(cloud.GOOGLE_REVOKE, data={"token": token["refresh_token"]})
                except httpx.HTTPError:
                    log.warning("could not ask Google to withdraw the sign-in; it is forgotten here")
        except CloudError as exc:
            if delete_files:
                raise ApiError(
                    502, "drive_unreachable", "Could not delete the files in Google Drive. Try again later."
                ) from exc
    _token_path(user.id).unlink(missing_ok=True)
    cancel(user.id)
    for item in db.scalars(select(DriveItem).where(DriveItem.user_id == user.id)):
        db.delete(item)
    if conn is not None:
        db.delete(conn)
    audit(
        db,
        actor_id=user.id,
        action="drive.disconnected",
        details={"provider": "google", "files": "deleted" if deleted else "kept"},
        request_id=request_id,
    )


# ---------------------------------------------------------------- views


def view(db: Session, user: User) -> dict[str, Any]:
    """What Settings shows. No token, no device code, no account details."""
    conn = connection(db, user.id)
    base: dict[str, Any] = {"available": cloud.configured(), "state": "off", "pending": None}
    if conn is None:
        return base | {"pending": pending(user.id)}
    files, size = db.execute(
        select(func.count(), func.coalesce(func.sum(DriveItem.byte_size), 0)).where(
            DriveItem.user_id == user.id, DriveItem.local_kind == "source"
        )
    ).one()
    not_yet, not_yet_bytes = _not_yet(db, conn)
    return base | {
        "state": conn.state,
        "connected_at": conn.connected_at.isoformat(),
        "folder": f"My Drive › {ROOT_NAME}",
        "mirror": conn.mirror,
        "exports": conn.exports,
        "files": int(files),
        "bytes": int(size),
        "not_yet": {"files": not_yet, "bytes": not_yet_bytes},
        "free_bytes": conn.free_bytes,
        "last_success_at": conn.last_success_at.isoformat() if conn.last_success_at else None,
        "progress": conn.progress,
        "error": conn.error if conn.state in ("failing", "revoked") else None,
        "next_try_at": conn.next_try_at.isoformat() if conn.next_try_at else None,
    }


def attention_item(db: Session, user: User) -> dict[str, Any] | None:
    conn = db.get(DriveConnection, user.id)
    if conn is None:
        return None
    item: dict[str, Any] = {"kind": "drive", "id": None, "course_id": None}
    if conn.state == "revoked":
        return item | {"title": "Your Google Drive copy stopped", "text": MESSAGES["revoked"]}
    if conn.state == "failing" and conn.failing_since and clock.now() - conn.failing_since >= cloud.ATTENTION_AFTER:
        return item | {
            "title": "Copying to your Google Drive is failing",
            "text": str((conn.error or {}).get("message")),
        }
    return None
