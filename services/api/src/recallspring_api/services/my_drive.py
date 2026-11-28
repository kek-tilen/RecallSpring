"""Your cloud folder (BYOS step 2, decided 2026-11-27): a readable copy of each learner's own material, by course,
and exports sent there when the learner chooses. Google Drive (My Drive › RecallSpring) or, since 2026-11-28, Dropbox
(Dropbox › Apps › RecallSpring › Material) or OneDrive (OneDrive › Apps › RecallSpring › Material); one at a time.

Each learner signs in with their own account (the same sign-in and app as the cloud copy of backups, cloud.py: Google
with scope ``drive.file``, only files RecallSpring made; Dropbox and OneDrive with an app folder, only that folder;
Dropbox with a code the learner pastes back, Google and OneDrive with a code typed at the provider). The refresh
token is kept per learner in
``secrets_dir/drive-<user id>.bin`` (DPAPI on Windows, 0600 elsewhere), never in the database, a backup, History, logs
or the browser. No account name or address is stored.

A synced folder (cloud_folder.py, 2026-11-28; iCloud Drive or any other sync app): the first account chooses one
folder on the computer RecallSpring runs on, and each learner who uses it gets a subfolder named by their sign-in name.
No sign-in and no token; the folder syncs to the account of whoever runs RecallSpring, and the page says so.

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

from .. import backup, clock, cloud, cloud_folder
from ..ai import siwc_store as store
from ..cloud import CloudError
from ..config import get_settings
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


def _messages(label: str) -> dict[str, str]:
    return {
        "revoked": f"{label} no longer allows RecallSpring. Your material is safe here; connect again to keep copying.",
        "no_room": f"Not enough room in your {label}. RecallSpring tries again tomorrow.",
        "unreachable": f"Could not reach {label}. RecallSpring tries again later.",
        "missing": f"A folder RecallSpring made in your {label} is gone. RecallSpring makes it again.",
        "busy": "A copy is running right now.",
    }


MESSAGES = _messages("Google Drive")


def _label(provider: str | None) -> str:
    return cloud.LABELS.get(provider or "google", "cloud folder")


def _error(exc: CloudError, provider: str | None = "google") -> CloudError:
    if provider == "folder" and exc.code not in ("busy", "missing"):
        return exc  # the folder's own message names the folder
    return CloudError(exc.code, _messages(_label(provider)).get(exc.code, exc.message))


FOLDER_REMOVED = (
    "Whoever runs this RecallSpring no longer offers the synced folder. Your material is safe here; disconnect and "
    "choose another cloud folder."
)


def _provider(name: str, root: str | None = None) -> Any:
    """The storage calls for one learner's run; a synced folder needs the folder the first account chose."""
    if name != "folder":
        return cloud.provider(name)
    base = cloud_folder.drive_base()
    if base is None:
        raise CloudError("folder_missing", FOLDER_REMOVED)
    return cloud_folder.Folder(base, drive_root=root or "")


# ---------------------------------------------------------------- secrets


def _token_path(user_id: uuid.UUID) -> Path:
    return store._dir() / f"drive-{user_id}.bin"


def _pending_path(user_id: uuid.UUID) -> Path:
    return store._dir() / f"drive-{user_id}-pending.bin"


def connection(db: Session, user_id: uuid.UUID) -> DriveConnection | None:
    row = db.get(DriveConnection, user_id)
    if row is not None and row.provider == "folder":
        return row  # no sign-in to keep
    return row if row is not None and _token_path(user_id).exists() else None


# ---------------------------------------------------------------- sign-in (as cloud.py: a code typed at Google or
# Microsoft, or the code Dropbox shows)


def start(user: User, provider: str = "google") -> dict[str, Any]:
    if provider == "dropbox":
        return _start_dropbox(user)
    pending = cloud.device_start(provider)
    cloud._write_secret(_pending_path(user.id), pending)
    return cloud._pending_view(pending)


def _start_dropbox(user: User) -> dict[str, Any]:
    from .. import cloud_dropbox

    verifier, challenge = cloud_dropbox.new_pkce()
    p = {
        "provider": "dropbox",
        "verifier": verifier,
        "authorize_url": cloud_dropbox.authorize_url(cloud._dropbox_key(), challenge),
        "expires_at": (clock.now() + cloud.DROPBOX_PENDING).isoformat(),
    }
    cloud._write_secret(_pending_path(user.id), p)
    return cloud._pending_view(p)


def pending(user_id: uuid.UUID) -> dict[str, Any] | None:
    p = cloud._read_secret(_pending_path(user_id))
    if p is None or not cloud._live(p):
        return None
    return cloud._pending_view(p)


def finish_dropbox(db: Session, user: User, code: str, request_id: str | None) -> None:
    """The code the learner pasted from Dropbox: connect, or CloudError (bad_code, expired)."""
    from .. import cloud_dropbox

    p = cloud._read_secret(_pending_path(user.id))
    if p is None or p.get("provider") != "dropbox" or not cloud._live(p):
        cancel(user.id)
        raise CloudError("expired", "This sign-in has expired. Start again for a new code.")
    with cloud._http() as http:
        body = cloud_dropbox.exchange(http, cloud._dropbox_key(), code.strip(), p["verifier"])
    _connected(db, user, "dropbox", {"refresh_token": body["refresh_token"]}, body["access_token"], request_id)


def _connected(db: Session, user: User, name: str, token: dict[str, Any], access: str, request_id: str | None) -> None:
    cancel(user.id)
    cloud._write_secret(_token_path(user.id), token | {"provider": name})
    try:
        p = cloud.provider(name)
        with cloud._http() as http:
            root = p.ensure_folder(http, access, p.drive_root, None)
    except CloudError:
        _token_path(user.id).unlink(missing_ok=True)
        raise
    _remember(db, user, name, root, request_id, {"provider": name})


def _remember(db: Session, user: User, name: str, root: str, request_id: str | None, details: dict[str, Any]) -> None:
    old = db.get(DriveConnection, user.id)
    if old is not None and old.provider != name:  # another provider than before: start over there
        for item in db.scalars(select(DriveItem).where(DriveItem.user_id == user.id)):
            db.delete(item)
        db.delete(old)
        db.flush()
        old = None
    if old is not None:  # signing in again after access was withdrawn keeps what was copied
        old.root_id, old.state, old.error, old.failures = root, "ok", None, 0
        old.failing_since = old.next_try_at = None
    else:
        # copy_from by the database clock, as Source.uploaded_at
        db.add(DriveConnection(user_id=user.id, provider=name, root_id=root, copy_from=func.now(), state="ok"))
    audit(db, actor_id=user.id, action="drive.connected", details=details, request_id=request_id)


# ---------------------------------------------------------------- a synced folder (cloud_folder.py, 2026-11-28)


def _is_first(db: Session, user: User) -> bool:
    """The first account chooses the folder: it is on the computer RecallSpring runs on."""
    return db.scalar(select(User.id).order_by(User.created_at, User.id).limit(1)) == user.id


def _subfolder(user: User) -> str:
    """The learner's sign-in name, made safe (connect_folder numbers it when another learner's folder has the same
    name regardless of letter case: two learners never share a folder)."""
    return safe_name(user.username, "learner", 64)


def folder_check(db: Session, user: User, raw: str | None) -> dict[str, Any]:
    if not _is_first(db, user):
        raise ApiError(403, "not_backup_owner", "Only the first account on this RecallSpring chooses the folder.")
    return cloud_folder.check(raw, "drive")


def set_folder(db: Session, user: User, raw: str | None, request_id: str | None) -> None:
    """The first account chooses (or, with None, stops offering) the synced folder learners' copies go under.
    Learners already using it keep their files; their copying stops with a plain message. Audited."""
    if not _is_first(db, user):
        raise ApiError(403, "not_backup_owner", "Only the first account on this RecallSpring chooses the folder.")
    if not cloud_folder.from_web():
        raise ApiError(
            409, "drive_folder_locked", "The folder is set in the server settings here (RS_DRIVE_FOLDER_DIR)."
        )
    config = backup.read_config()
    old = config.get("drive_folder")
    if raw is None:
        config.pop("drive_folder", None)
        new: str | None = None
    else:
        try:
            new = str(cloud_folder.prepare(raw, "drive"))
        except CloudError as exc:
            raise ApiError(422, f"drive_{exc.code}", exc.message) from exc
        config["drive_folder"] = new
    backup._write_json(get_settings().backup_settings_file, config)
    audit(
        db,
        actor_id=user.id,
        action="drive.folder_changed",
        details={"from": old, "to": new, "sync": cloud_folder.app_of(Path(new)) if new else None},
        request_id=request_id,
    )


def connect_folder(db: Session, user: User, request_id: str | None) -> None:
    """Use the synced folder: the learner's own subfolder in it, made now (never the folder above it)."""
    base = cloud_folder.drive_base()
    if base is None:
        raise CloudError("folder_missing", "Whoever runs this RecallSpring has not chosen a synced folder yet.")
    name = _subfolder(user)
    others = {
        r.lower()
        for r in db.scalars(
            select(DriveConnection.root_id).where(
                DriveConnection.provider == "folder", DriveConnection.user_id != user.id
            )
        )
    }
    p = cloud_folder.Folder(base)
    if name.lower() in others:
        root = p.new_folder(None, "", name, "")  # numbered: "maja (1)"
    else:
        root = p.ensure_folder(None, "", name, None)
    cancel(user.id)
    _token_path(user.id).unlink(missing_ok=True)  # a sign-in kept from before (access withdrawn) is not needed now
    _remember(
        db,
        user,
        "folder",
        root,
        request_id,
        {"provider": "folder", "folder": str(base / root), "sync": cloud_folder.app_of(base)},
    )


def cancel(user_id: uuid.UUID) -> None:
    _pending_path(user_id).unlink(missing_ok=True)


def poll(db: Session, user: User, request_id: str | None) -> str:
    """One check whether the learner finished signing in at Google or Microsoft: pending, connected, denied, expired,
    blocked (the organisation blocks this sign-in) or not_supported (the account refuses the app folder)."""
    p = cloud._read_secret(_pending_path(user.id))
    name = (p or {}).get("provider", "google")
    if p is None or name not in cloud.DEVICE_PROVIDERS:
        return "expired"
    p.setdefault("provider", name)
    state, body = cloud.device_check(p, lambda q: cloud._write_secret(_pending_path(user.id), q))
    if state == "pending":
        return state
    if state != "connected" or body is None:
        cancel(user.id)
        return state
    try:
        _connected(db, user, name, cloud.device_token(name, body), body["access_token"], request_id)
    except CloudError as exc:
        if exc.code != "not_supported":
            raise
        return "not_supported"
    return "connected"


# ---------------------------------------------------------------- copy runs


class _Run:
    """One copy run for one learner: folder ids are checked once per run (a folder deleted in the cloud is made
    again)."""

    def __init__(self, db: Session, http: httpx.Client, p: Any, token: str, conn: DriveConnection) -> None:
        self.db, self.http, self.p, self.token, self.conn = db, http, p, token, conn
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
            found = self.p.get(self.http, self.token, self.conn.root_id)
            if found is None or found.get("trashed"):
                # The whole folder is gone: make it again and copy everything again.
                self.conn.root_id = self.p.ensure_folder(self.http, self.token, self.p.drive_root, None)
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
            found = self.p.get(self.http, self.token, item.drive_id)
            if found is None or found.get("trashed"):
                self.db.delete(item)
                self._forget_under(kind, local_id)
                self.db.flush()
                item = None
            elif item.name != name:  # renamed in RecallSpring: rename in the cloud too
                moved = self.p.rename(self.http, self.token, item.drive_id, name)
                if isinstance(moved, str) and moved != item.drive_id:  # a synced folder: refs are paths
                    self._moved(item.drive_id, moved)
                    item.drive_id = moved
                item.name = name
        if item is None:
            item = DriveItem(
                user_id=self.conn.user_id,
                local_kind=kind,
                local_id=local_id,
                drive_id=self.p.new_folder(self.http, self.token, name, parent),
                name=name,
            )
            self.db.add(item)
            self.db.flush()
        self.checked[key] = item.drive_id
        return item.drive_id

    def _moved(self, old: str, new: str) -> None:
        """What was copied under a renamed folder keeps its place (path references change with the folder)."""
        under = select(DriveItem).where(
            DriveItem.user_id == self.conn.user_id, DriveItem.drive_id.startswith(old + "/", autoescape=True)
        )
        for row in self.db.scalars(under):
            row.drive_id = new + row.drive_id[len(old) :]
        self.checked = {k: (new + v[len(old) :] if v.startswith(old + "/") else v) for k, v in self.checked.items()}

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
        size = self.p.upload(self.http, self.token, path, parent, on_bytes, name=name, file_id=ids)
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
            raise CloudError("busy", "A copy is running right now.") from exc
        with conn:
            key = {"a": LOCK_ID, "b": int.from_bytes(user_id.bytes[:4], "big", signed=True)}
            got = conn.execute(text("SELECT pg_try_advisory_lock(:a, :b)"), key).scalar_one()
            conn.commit()
            if not got:
                raise CloudError("busy", "A copy is running right now.")
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
    with new_session() as db:
        row = db.get(DriveConnection, user_id)
        provider = row.provider if row is not None else "google"
    try:
        with _locked(user_id):
            return _sync(user_id)
    except CloudError as exc:
        return "busy" if exc.code == "busy" else _failed(user_id, _error(exc, provider))
    except Exception:  # noqa: BLE001 - the worker must keep running
        log.exception("drive copy crashed")
        return _failed(user_id, CloudError("unreachable", _messages(_label(provider))["unreachable"]))


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
            p = _provider(conn.provider, conn.root_id)
            token = p.access_token(http, _token_path(user_id))
            run = _Run(db, http, p, token, conn)
            free = p.free_bytes(http, token)
            if free is not None and free < total_bytes:
                raise CloudError("no_room", _messages(p.label)["no_room"])
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
            conn.free_bytes = p.free_bytes(http, token)
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
            audit(db, actor_id=user_id, action="drive.failed", details={"provider": conn.provider, "code": exc.code})
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
    """Upload a finished export to the learner's cloud folder › Exports. Returns None, or an error code."""
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
                p = _provider(conn.provider, conn.root_id)
                token = p.access_token(http, _token_path(row.user_id))
                run = _Run(db, http, p, token, conn)
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
            with new_session() as db:
                row_conn = db.get(DriveConnection, user_id)
                name = row_conn.provider if row_conn is not None else "google"
            _failed(user_id, _error(exc, name))  # the row and Today say so too
        return exc.code
    except Exception:  # noqa: BLE001
        log.exception("export to drive crashed")
        return "unreachable"


# ---------------------------------------------------------------- settings


def set_options(db: Session, user: User, *, mirror: bool | None, exports: bool | None) -> DriveConnection:
    conn = connection(db, user.id)
    if conn is None:
        raise ApiError(409, "drive_not_connected", "Connect your cloud folder first.")
    if mirror is not None:
        conn.mirror = mirror
    if exports is not None:
        conn.exports = exports
    return conn


def copy_existing(db: Session, user: User, request_id: str | None) -> tuple[int, int]:
    conn = connection(db, user.id)
    if conn is None:
        raise ApiError(409, "drive_not_connected", "Connect your cloud folder first.")
    n, size = _not_yet(db, conn)
    conn.copy_from, conn.mirror, conn.next_try_at = None, True, None
    audit(
        db, actor_id=user.id, action="drive.copy_existing", details={"files": n, "bytes": size}, request_id=request_id
    )
    return n, size


def disconnect(db: Session, user: User, delete_files: bool, request_id: str | None) -> None:
    """Forget the sign-in and ask the provider to withdraw it; the files stay unless ``delete_files`` (asked once
    more)."""
    conn = db.get(DriveConnection, user.id)
    token = cloud._read_secret(_token_path(user.id))
    name = conn.provider if conn is not None else "google"
    deleted = False
    if conn is not None and name == "folder":
        if delete_files:
            try:
                _provider(name, conn.root_id).delete(None, "", conn.root_id)
            except CloudError as exc:
                raise ApiError(
                    502, "drive_unreachable", f"Could not delete the files in the synced folder: {exc.message}"
                ) from exc
            deleted = True
    elif conn is not None and token:
        try:
            p = cloud.provider(name)
            with cloud._http() as http:
                if delete_files:
                    access = p.access_token(http, _token_path(user.id))
                    p.delete(http, access, conn.root_id)
                    deleted = True
                try:
                    p.revoke(http, _token_path(user.id))
                except (httpx.HTTPError, CloudError):
                    log.warning("could not ask %s to withdraw the sign-in; it is forgotten here", p.label)
        except CloudError as exc:
            if delete_files:
                raise ApiError(
                    502, "drive_unreachable", f"Could not delete the files in {_label(name)}. Try again later."
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
        details={"provider": name, "files": "deleted" if deleted else "kept"},
        request_id=request_id,
    )


# ---------------------------------------------------------------- views


def view(db: Session, user: User) -> dict[str, Any]:
    """What Settings shows. No token, no device code, no account details."""
    conn = connection(db, user.id)
    chosen = cloud_folder.drive_base()
    first = _is_first(db, user)
    can_choose = first and cloud_folder.from_web()
    base: dict[str, Any] = {
        "available": {name: cloud.configured(name) for name in cloud.PROVIDERS} | {"folder": chosen is not None},
        "state": "off",
        "provider": None,
        "pending": None,
        "synced_folder": {
            "path": str(chosen) if chosen and first else None,  # the server's own path: only for the first account
            "where": cloud_folder.display(chosen) if chosen else None,
            "mine": cloud_folder.display(chosen / _subfolder(user)) if chosen else None,
            "sync": cloud_folder.app_of(chosen) if chosen else None,
            "can_choose": can_choose,
            "suggestions": cloud_folder.suggestions() if can_choose and chosen is None else [],
        },
    }
    if conn is None:
        return base | {"pending": pending(user.id)}
    if conn.provider == "folder":
        p = None
        where = cloud_folder.display(chosen / conn.root_id) if chosen else None
    else:
        p = cloud.provider(conn.provider) if cloud.configured(conn.provider) else None
        where = p.where + (f" › {p.drive_root}" if conn.provider != "google" else "") if p else None
    files, size = db.execute(
        select(func.count(), func.coalesce(func.sum(DriveItem.byte_size), 0)).where(
            DriveItem.user_id == user.id, DriveItem.local_kind == "source"
        )
    ).one()
    not_yet, not_yet_bytes = _not_yet(db, conn)
    return base | {
        "state": conn.state,
        "provider": conn.provider,
        "connected_at": conn.connected_at.isoformat(),
        "folder": where,
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
    label = _label(conn.provider)
    if conn.state == "failing" and (conn.error or {}).get("code") == "folder_missing":  # at once: nothing is copied
        return item | {"title": "Your synced folder copy is waiting", "text": str((conn.error or {}).get("message"))}
    if conn.state == "revoked":
        return item | {"title": f"Your {label} copy stopped", "text": _messages(label)["revoked"]}
    if conn.state == "failing" and conn.failing_since and clock.now() - conn.failing_since >= cloud.ATTENTION_AFTER:
        return item | {
            "title": f"Copying to your {label} is failing",
            "text": str((conn.error or {}).get("message")),
        }
    return None
