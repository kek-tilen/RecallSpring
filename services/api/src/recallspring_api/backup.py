"""Backups of the database and the uploaded files (docs/08 -> Backups). No model calls, no network.

Layout under ``backup_dir`` (other files there, e.g. hand-made ``*.dump`` files, are never touched)::

    snapshots/<YYYYMMDD-HHMMSS>/db.dump        pg_dump custom format, taken from one database snapshot (UTC name)
    snapshots/<YYYYMMDD-HHMMSS>/manifest.json  row counts per table, alembic version, files, check result
    files/<user>/<ab>/<sha256>                 uploaded originals, shared by all snapshots (content-addressed)
    status.json                                last attempt and last good backup, shown in Settings

The row counts and the list of files are read in the same REPEATABLE READ transaction whose snapshot pg_dump uses
(``--snapshot``), so the check can compare exactly: the dump is restored into a throwaway database
``<db>_restore_check`` and every table must have the same number of rows. Files are copied once and checked
against their SHA-256 (their name). Old snapshots are thinned to the newest per day for ``backup_keep_daily`` days
and the newest per week for ``backup_keep_weekly`` weeks; files no kept snapshot needs are removed.

Restoring never overwrites anything: ``restore`` creates a new database (and optionally fills an empty storage
folder); switching RecallSpring to it is a deliberate step by the owner (docs/08).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, make_url, text
from sqlalchemy.engine import URL, Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from . import __version__, clock
from .config import get_settings

log = logging.getLogger(__name__)

LOCK_ID = 727_170_001  # pg advisory lock: one backup at a time per database
SNAPSHOT_RE = re.compile(r"^\d{8}-\d{6}$")
NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
KEY_RE = re.compile(r"^[0-9a-f-]{36}/[0-9a-f]{2}/[0-9a-f]{64}$")
CHECK_SUFFIX = "_restore_check"
STAMP = "%Y%m%d-%H%M%S"
RETRY_AFTER_FAILURE = timedelta(hours=1)


class BackupError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


# ---------------------------------------------------------------- paths and status


def server_root() -> Path:
    """The folder the server settings give (RS_BACKUP_DIR), else ``backups`` next to the uploads."""
    s = get_settings()
    return s.backup_dir if s.backup_dir is not None else s.storage_dir.parent / "backups"


def read_config() -> dict[str, Any]:
    """What was chosen in Settings (backup_settings_file). Unreadable means nothing was chosen."""
    try:
        data = json.loads(get_settings().backup_settings_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _chosen_dir() -> Path | None:
    if not get_settings().backup_settings_from_web:
        return None
    value = read_config().get("dir")
    return Path(value) if isinstance(value, str) and value and Path(value).is_absolute() else None


def backup_root() -> Path:
    """A folder chosen in Settings, else the server's (2026-11-27)."""
    return _chosen_dir() or server_root()


def location_source() -> str:
    if _chosen_dir() is not None:
        return "settings"
    return "server" if get_settings().backup_dir is not None else "default"


def _status_path() -> Path:
    return backup_root() / "status.json"


def read_status() -> dict[str, Any]:
    try:
        data = json.loads(_status_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) and value else None
    except ValueError:
        return None


def snapshots() -> list[Path]:
    """Complete snapshots, oldest first."""
    root = backup_root() / "snapshots"
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and SNAPSHOT_RE.match(p.name))


def _existing_ancestor(path: Path) -> Path:
    path = path.resolve()
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _same_disk(a: Path, b: Path) -> bool:
    try:
        return os.stat(_existing_ancestor(a)).st_dev == os.stat(_existing_ancestor(b)).st_dev
    except OSError:
        return True


def status_view() -> dict[str, Any]:
    """What Settings shows. Never contains secrets (no database URL, no password)."""
    s = get_settings()
    st = read_status()
    kept = snapshots()
    files_dir = backup_root() / "files"
    disk = sum(f.stat().st_size for f in files_dir.rglob("*") if f.is_file()) if files_dir.is_dir() else 0
    disk += sum((p / "db.dump").stat().st_size for p in kept if (p / "db.dump").is_file())
    last_success = _parse(st.get("last_success_at"))
    next_due = None
    if s.backup_enabled:
        next_due = (last_success + timedelta(hours=s.backup_interval_hours)).isoformat() if last_success else "now"
    return {
        "enabled": s.backup_enabled,
        "location": str(backup_root()),
        "location_source": location_source(),
        "server_location": str(server_root()),
        "folder_from_web": s.backup_settings_from_web,
        "sync": sync_provider(backup_root()),
        "same_disk_as_storage": _same_disk(backup_root(), s.storage_dir),
        "interval_hours": s.backup_interval_hours,
        "keep_daily": s.backup_keep_daily,
        "keep_weekly": s.backup_keep_weekly,
        "last_attempt_at": st.get("last_attempt_at"),
        "last_success_at": st.get("last_success_at"),
        "last_error": st.get("last_error") if _failed_last(st) else None,
        "last": st.get("last"),
        "next_due": next_due,
        "snapshots": [p.name for p in reversed(kept)],
        "disk_bytes": disk,
        "tools": tools_label(),
    }


def _failed_last(st: dict[str, Any]) -> bool:
    error = st.get("last_error")
    if not isinstance(error, dict):
        return False
    last_success, failed_at = _parse(st.get("last_success_at")), _parse(error.get("at"))
    return last_success is None or failed_at is None or failed_at >= last_success


def attention_item() -> dict[str, Any] | None:
    """A "Needs attention" entry when backups fail or are overdue (two intervals without a good one)."""
    s = get_settings()
    if not s.backup_enabled:
        return None
    st = read_status()
    item: dict[str, Any] = {"kind": "backup", "id": None, "course_id": None}
    if _failed_last(st):
        message = str(st["last_error"].get("message", "")).strip()
        return item | {
            "title": "The last backup failed",
            "text": f"{message} RecallSpring tries again within an hour; Settings → Backups has details.",
        }
    last_success = _parse(st.get("last_success_at"))
    if last_success is None:
        return item | {
            "title": "No backup yet",
            "text": "The first one runs by itself while RecallSpring runs, or use Back up now in Settings → Backups.",
        }
    age = clock.now() - last_success
    if age > timedelta(hours=2 * s.backup_interval_hours):
        days = age.days
        return item | {
            "title": f"No backup for {days} day{'s' if days != 1 else ''}",
            "text": "Backups run while the RecallSpring worker runs. Use Back up now in Settings → Backups.",
        }
    return None


# ---------------------------------------------------------------- PostgreSQL tools


@dataclass(frozen=True)
class PgTools:
    mode: str  # "bin" or "docker"
    pg_dump: list[str]
    pg_restore: list[str]

    def env(self, url: URL) -> dict[str, str]:
        """Connection details go in the environment, so the password is never on a command line. Inside the
        Docker container the local socket is used (no password)."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
        if self.mode == "bin":
            env.update(
                PGHOST=url.host or "127.0.0.1",
                PGPORT=str(url.port or 5432),
                PGUSER=url.username or "",
                PGPASSWORD=url.password or "",
            )
        return env

    def args(self, url: URL, database: str) -> list[str]:
        if self.mode == "docker":
            return ["-U", url.username or "postgres", "-d", database]
        return ["-d", database]


def _exe(folder: Path, name: str) -> Path:
    return folder / (f"{name}.exe" if os.name == "nt" else name)


def find_tools() -> PgTools | None:
    """pg_dump/pg_restore from RS_BACKUP_PG_BIN, else PATH, else (development only) the dev database container.
    Production images ship the client tools; the Docker socket is never used there."""
    s = get_settings()
    if s.backup_pg_bin is not None:
        dump, restore = _exe(s.backup_pg_bin, "pg_dump"), _exe(s.backup_pg_bin, "pg_restore")
        return PgTools("bin", [str(dump)], [str(restore)]) if dump.is_file() and restore.is_file() else None
    dump_path, restore_path = shutil.which("pg_dump"), shutil.which("pg_restore")
    if dump_path and restore_path:
        return PgTools("bin", [dump_path], [restore_path])
    docker = shutil.which("docker")
    if docker and s.backup_docker_container and s.environment in ("development", "test"):
        c = s.backup_docker_container
        return PgTools("docker", [docker, "exec", "-i", c, "pg_dump"], [docker, "exec", "-i", c, "pg_restore"])
    return None


def tools_label() -> str | None:
    tools = find_tools()
    if tools is None:
        return None
    if tools.mode == "docker":
        return f"pg_dump in the Docker container {get_settings().backup_docker_container}"
    return f"pg_dump at {tools.pg_dump[0]}"


def _safe(message: str) -> str:
    password = make_url(get_settings().database_url).password
    if password:
        message = message.replace(password, "***")
    return message[:300]


def _run(
    label: str, cmd: list[str], *, env: dict[str, str], stdin: Path | None = None, stdout: Path | None = None
) -> None:
    timeout = get_settings().backup_timeout_seconds
    fin = open(stdin, "rb") if stdin else None  # noqa: SIM115
    fout = open(stdout, "wb") if stdout else None  # noqa: SIM115
    try:
        proc = subprocess.run(  # noqa: S603 - fixed tool paths; arguments are never shell-interpreted
            cmd,
            stdin=fin or subprocess.DEVNULL,
            stdout=fout or subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise BackupError("timeout", f"{label} did not finish within {timeout} seconds.") from exc
    except OSError as exc:
        raise BackupError("tool_failed", f"Could not start {label}: {exc.strerror}.") from exc
    finally:
        for f in (fin, fout):
            if f:
                f.close()
    if proc.returncode != 0:
        lines = [ln for ln in proc.stderr.decode("utf-8", "replace").splitlines() if ln.strip()]
        raise BackupError("tool_failed", _safe(f"{label} failed: {lines[-1].strip() if lines else 'no details'}"))


# ---------------------------------------------------------------- one backup


def _db_url() -> URL:
    return make_url(get_settings().database_url)


def _tables(conn: Connection) -> list[str]:
    rows = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"))
    return [r[0] for r in rows if NAME_RE.match(r[0])]


def _counts(conn: Connection) -> dict[str, int]:
    return {t: int(conn.execute(text(f'SELECT count(*) FROM "{t}"')).scalar_one()) for t in _tables(conn)}


def _audit(actor_id: uuid.UUID | None, action: str, details: dict[str, Any], request_id: str | None) -> None:
    from .db import new_session
    from .services.events import audit

    try:
        with new_session() as db:
            audit(db, actor_id=actor_id, action=action, target_type="backup", details=details, request_id=request_id)
            db.commit()
    except SQLAlchemyError:
        log.warning("could not write the backup audit event", exc_info=True)


def run(
    reason: str = "scheduled", *, actor_id: uuid.UUID | None = None, request_id: str | None = None
) -> dict[str, Any]:
    """Make one backup now and return the new status view. Failures are recorded (status.json, audit) and raised
    as BackupError; "busy" (another backup is running) is neither recorded nor audited."""
    try:
        with _locked() as engine:
            return _run_locked(engine, reason, actor_id, request_id)
    except BackupError as exc:
        if exc.code == "database_unreachable":
            _record_failure(clock.now(), exc, reason, actor_id, request_id)
        raise


@contextmanager
def _locked() -> Iterator[Engine]:
    """One backup (or folder change) at a time: a PostgreSQL advisory lock held for the duration."""
    engine = create_engine(_db_url(), pool_pre_ping=True)
    try:
        try:
            lock_conn = engine.connect()
        except SQLAlchemyError as exc:
            raise BackupError("database_unreachable", "Could not connect to the database.") from exc
        with lock_conn:
            got = lock_conn.execute(text("SELECT pg_try_advisory_lock(:id)"), {"id": LOCK_ID}).scalar_one()
            lock_conn.commit()
            if not got:
                raise BackupError("busy", "Another backup is running right now; try again in a minute.")
            try:
                yield engine
            finally:
                lock_conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
                lock_conn.commit()
    finally:
        engine.dispose()


def _record_failure(
    started: datetime, error: BackupError, reason: str, actor_id: uuid.UUID | None, request_id: str | None
) -> None:
    status = read_status()
    status["last_attempt_at"] = started.isoformat()
    status["last_error"] = {"code": error.code, "message": error.message, "at": started.isoformat(), "reason": reason}
    try:
        _write_json(_status_path(), status)
    except OSError:
        log.warning("could not write the backup status", exc_info=True)
    _audit(actor_id, "backup.failed", {"code": error.code, "message": error.message, "reason": reason}, request_id)
    log.warning("backup failed (%s): %s", error.code, error.message)


def _free_name(started: datetime) -> str:
    root = backup_root() / "snapshots"
    name = started.strftime(STAMP)
    while (root / name).exists() or (root / f".partial-{name}").exists():
        started += timedelta(seconds=1)
        name = started.strftime(STAMP)
    return name


def _run_locked(engine: Engine, reason: str, actor_id: uuid.UUID | None, request_id: str | None) -> dict[str, Any]:
    s = get_settings()
    root = backup_root()
    started = clock.now()
    partial: Path | None = None
    try:
        tools = find_tools()
        if tools is None:
            raise BackupError(
                "no_pg_dump",
                "pg_dump was not found (not on PATH and RS_BACKUP_PG_BIN is not set). Install the PostgreSQL client "
                "tools in the same major version as the database server.",
            )
        url = _db_url()
        name = _free_name(started)
        partial = root / "snapshots" / f".partial-{name}"
        partial.mkdir(parents=True)
        dump = partial / "db.dump"
        manifest = _dump(engine, tools, url, dump)
        keys = manifest.pop("_keys")
        manifest.update(name=name, created_at=started.isoformat(), reason=reason, app_version=__version__)
        manifest["files"] = _copy_files(keys, root / "files")
        manifest["dump_bytes"] = dump.stat().st_size
        manifest["check"] = _check(tools, url, dump, manifest["counts"]) if s.backup_verify else {"method": "none"}
        _write_json(partial / "manifest.json", manifest)
        os.replace(partial, root / "snapshots" / name)
        partial = None
        removed = prune()
        files = manifest["files"]
        last = {
            "snapshot": name,
            "reason": reason,
            "tables": len(manifest["counts"]),
            "rows": sum(manifest["counts"].values()),
            "files": files["count"],
            "files_copied": files["copied"],
            "files_missing": files["missing"],
            "files_bytes": files["bytes"],
            "dump_bytes": manifest["dump_bytes"],
            "check": manifest["check"]["method"],
            "removed_snapshots": removed,
            "seconds": round((clock.now() - started).total_seconds(), 1),
        }
        status = read_status()
        status.update(last_attempt_at=started.isoformat(), last_success_at=started.isoformat(), last=last)
        _write_json(_status_path(), status)
        _audit(actor_id, "backup.created", last, request_id)
        log.info("backup %s done: %s rows, %s files, check %s", name, last["rows"], last["files"], last["check"])
        return status_view()
    except BackupError as exc:
        _record_failure(started, exc, reason, actor_id, request_id)
        raise
    except Exception as exc:  # unexpected: recorded without details that could hold secrets
        log.exception("backup failed unexpectedly")
        error = BackupError("unexpected", _safe(f"Unexpected error: {type(exc).__name__}."))
        _record_failure(started, error, reason, actor_id, request_id)
        raise error from exc
    finally:
        if partial is not None:
            shutil.rmtree(partial, ignore_errors=True)


def _dump(engine: Engine, tools: PgTools, url: URL, target: Path) -> dict[str, Any]:
    """Row counts, file list and the dump, all from one database snapshot."""
    database = url.database or ""
    with engine.connect().execution_options(isolation_level="REPEATABLE READ") as conn:
        snapshot_id = conn.execute(text("SELECT pg_export_snapshot()")).scalar_one()
        counts = _counts(conn)
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        keys = sorted({r[0] for r in conn.execute(text("SELECT storage_key FROM sources"))})
        _run(
            "pg_dump",
            [*tools.pg_dump, *tools.args(url, database), "--format=custom", "--no-owner", f"--snapshot={snapshot_id}"],
            env=tools.env(url),
            stdout=target,
        )
        conn.rollback()
    return {"database": database, "alembic_version": version, "counts": counts, "_keys": keys}


def _copy_verified(src: Path, dest: Path, sha256: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.tmp")
    digest = hashlib.sha256()
    with open(src, "rb") as fin, open(tmp, "wb") as fout:
        while chunk := fin.read(1024 * 1024):
            digest.update(chunk)
            fout.write(chunk)
    if digest.hexdigest() != sha256:
        tmp.unlink(missing_ok=True)
        raise BackupError("file_corrupt", f"An uploaded file does not match its checksum ({sha256[:12]}…).")
    os.replace(tmp, dest)


def _copy_files(keys: list[str], files_dir: Path) -> dict[str, Any]:
    """Copy each original once (content-addressed). A file missing from storage but kept by an earlier backup
    stays listed; one missing everywhere is counted and reported."""
    storage = get_settings().storage_dir
    copied = missing = total = 0
    listed: list[str] = []
    for key in keys:
        if not KEY_RE.match(key):
            continue
        src, dest = storage / key, files_dir / key
        if dest.is_file() and (not src.is_file() or dest.stat().st_size == src.stat().st_size):
            listed.append(key)
            total += dest.stat().st_size
            continue
        if not src.is_file():
            missing += 1
            continue
        _copy_verified(src, dest, key.rsplit("/", 1)[1])
        listed.append(key)
        total += dest.stat().st_size
        copied += 1
    return {"count": len(listed), "copied": copied, "missing": missing, "bytes": total, "keys": listed}


def _admin_engine(url: URL) -> Engine:
    return create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")


def _check_name(database: str) -> str:
    name = f"{database}{CHECK_SUFFIX}"
    if not NAME_RE.match(name) or name == database or len(name) > 63:
        raise BackupError("invalid_name", "The database name cannot be used for a restore check.")
    return name


def _restored_counts(url: URL, database: str) -> dict[str, int]:
    engine = create_engine(url.set(database=database))
    try:
        with engine.connect() as conn:
            return _counts(conn)
    finally:
        engine.dispose()


def _check(tools: PgTools, url: URL, dump: Path, counts: dict[str, int]) -> dict[str, Any]:
    """Restore into a throwaway database and compare every table's row count. Without permission to create a
    database, the dump's table of contents is read instead (weaker, and reported as such)."""
    name = _check_name(url.database or "")
    admin = _admin_engine(url)
    try:
        try:
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
                conn.execute(text(f'CREATE DATABASE "{name}"'))
        except SQLAlchemyError:  # e.g. no CREATEDB permission on a hosted database
            _run("pg_restore --list", [*tools.pg_restore, "--list"], env=tools.env(url), stdin=dump)
            return {"method": "listed", "note": "No permission to create a check database; the dump was only read."}
        try:
            _run(
                "pg_restore",
                [*tools.pg_restore, *tools.args(url, name), "--no-owner", "--exit-on-error"],
                env=tools.env(url),
                stdin=dump,
            )
            restored = _restored_counts(url, name)
        finally:
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()
    different = sorted(t for t in counts if restored.get(t) != counts[t])
    if different:
        raise BackupError(
            "check_failed", f"The restored copy differs in {len(different)} table(s): {', '.join(different[:5])}."
        )
    return {"method": "restored", "tables": len(restored), "rows": sum(restored.values())}


# ---------------------------------------------------------------- choosing the folder (Settings, 2026-11-27)

GIB = 1024**3
# Folder names sync apps use; a hint only (only the sync app knows whether it really uploads).
_SYNC = (
    ("Dropbox", lambda part: part.startswith("dropbox")),
    ("OneDrive", lambda part: part.startswith("onedrive")),
    ("Google Drive", lambda part: part in ("google drive", "my drive") or part.startswith("googledrive")),
    ("iCloud Drive", lambda part: part in ("icloud drive", "iclouddrive", "com~apple~clouddocs")),
)
_POSIX_SYSTEM = ("/bin", "/boot", "/dev", "/etc", "/lib", "/lib32", "/lib64", "/proc", "/run", "/sbin", "/sys", "/usr")
_POSIX_TOP = {"/", "/home", "/mnt", "/media", "/opt", "/root", "/srv", "/tmp", "/var", "/Users", "/Volumes"}


def sync_provider(path: Path) -> str | None:
    parts = [x.lower() for x in path.parts]
    for name, match in _SYNC:
        if any(match(x) for x in parts):
            return name
    return None


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _system_refusal(p: Path) -> str | None:
    if os.name == "nt":
        if p == Path(p.anchor):
            return "Choose a folder, not a whole drive."
        windir = Path(os.environ.get("SystemRoot") or os.environ.get("WINDIR") or "C:\\Windows")
        system = [windir]
        names = ("ProgramFiles", "ProgramFiles(x86)", "ProgramData")
        system += [Path(os.environ[v]) for v in names if os.environ.get(v)]
        if any(_inside(p, x.resolve()) for x in system):
            return "That is a system folder; choose a folder of your own."
        return None
    posix = p.as_posix()
    if posix in _POSIX_TOP:
        return "Choose a folder of its own, not a top-level folder."
    if any(posix == x or posix.startswith(x + "/") for x in _POSIX_SYSTEM):
        return "That is a system folder; choose a folder of your own."
    return None


def _place_refusal(p: Path) -> str | None:
    s = get_settings()
    if refusal := _system_refusal(p):
        return refusal
    for other, what in ((s.storage_dir, "your uploaded files"), (s.secrets_dir, "the sign-in secrets")):
        o = other.resolve()
        if _inside(p, o) or _inside(o, p):
            return f"That folder holds or is inside {what}; backups need a folder of their own."
    return None


def _writable(folder: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(dir=folder, prefix=".recallspring-write-check-"):
            return True
    except OSError:
        return False


def check_folder(raw: str | None) -> dict[str, Any]:
    """Try a folder before it is saved: can RecallSpring write there, how much room is free, another disk than the
    uploads, and whether a sync app copies it elsewhere. Creates nothing (the write check leaves no file)."""
    checks: list[dict[str, str]] = []

    def add(check: str, level: str, message: str) -> None:
        checks.append({"id": check, "level": level, "text": message})

    def result(p: Path | None = None, **extra: Any) -> dict[str, Any]:
        return {
            "path": str(p) if p else None,
            "ok": all(c["level"] != "bad" for c in checks),
            "checks": checks,
            **extra,
        }

    value = (raw or "").strip().strip('"').strip()
    if not value:
        add("path", "bad", "Type the full path of a folder.")
        return result()
    if len(value) > 1000 or "\x00" in value:
        add("path", "bad", "That path is too long.")
        return result()
    given = Path(value).expanduser()
    if not given.is_absolute():
        add("path", "bad", "Use the full path, starting with a drive letter (D:\\…) or with /.")
        return result()
    p = given.resolve()
    if refusal := _place_refusal(p):
        add("place", "bad", refusal)
        return result(p)
    if p.exists() and not p.is_dir():
        add("place", "bad", "That is a file, not a folder.")
        return result(p)
    base = _existing_ancestor(p)
    if not base.is_dir() or not _writable(base):
        add("write", "bad", "RecallSpring cannot write there. Check the folder exists and may be written to.")
        return result(p)
    free = shutil.disk_usage(base).free
    needed = max(GIB, 2 * _folder_bytes(backup_root()))
    room = f"{free / GIB:,.0f} GB free" if free >= GIB else f"{free / 1024**2:,.0f} MB free"
    where = "RecallSpring can write here" if p.exists() else "RecallSpring can make this folder"
    tight = free < needed
    add("write", "warn" if tight else "ok", f"{where} · {room}" + (", which is tight" if tight else ""))
    same = _same_disk(p, get_settings().storage_dir)
    if same:
        add("disk", "warn", "Same disk as your uploads: a broken disk would take both")
    else:
        add("disk", "ok", "Another disk than your uploads, so a broken disk does not take both")
    provider = sync_provider(p)
    if provider:
        add("sync", "ok", f"Looks like a {provider} folder: copies leave this computer when {provider} syncs")
    if p == backup_root().resolve():
        add("current", "ok", "This is the folder backups go to now")
    return result(p, exists=p.exists(), free_bytes=free, same_disk=same, sync=provider)


def _folder_bytes(root: Path) -> int:
    total = 0
    for sub in ("files", "snapshots"):
        d = root / sub
        if d.is_dir():
            total += sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    return total


def set_folder(raw: str | None, *, actor_id: uuid.UUID | None = None, request_id: str | None = None) -> dict[str, Any]:
    """Save the folder chosen in Settings (None: back to the server's). Waits for no backup: refused while one runs.
    Backups already made stay where they are. Audited as ``backup.folder_changed``."""
    s = get_settings()
    if not s.backup_settings_from_web:
        raise BackupError("folder_locked", "The backup folder is set in the server settings here (RS_BACKUP_DIR).")
    old = backup_root()
    with _locked():
        config = read_config()
        if raw is None:
            config.pop("dir", None)
            new = server_root()
        else:
            check = check_folder(raw)
            if not check["ok"]:
                bad = next(c["text"] for c in check["checks"] if c["level"] == "bad")
                raise BackupError("folder_refused", bad)
            new = Path(check["path"])
            new.mkdir(parents=True, exist_ok=True)
            config["dir"] = str(new)
        config["dir_changed_at"] = clock.now().isoformat()
        _write_json(s.backup_settings_file, config)
    _audit(
        actor_id,
        "backup.folder_changed",
        {"from": str(old), "to": str(new), "source": location_source(), "sync": sync_provider(new)},
        request_id,
    )
    return status_view()


# ---------------------------------------------------------------- retention


def keep_names(names: list[str], now: datetime) -> set[str]:
    """The newest snapshot of each of the last ``keep_daily`` days and of the newest ``keep_weekly`` ISO weeks
    that have one; the newest snapshot is always kept."""
    s = get_settings()
    if not names:
        return set()
    stamps = {n: datetime.strptime(n, STAMP) for n in names}
    keep = {max(names)}
    by_day: dict[Any, str] = {}
    by_week: dict[Any, str] = {}
    for n in sorted(names):  # later ones win: newest per day and per week
        by_day[stamps[n].date()] = n
        by_week[tuple(stamps[n].isocalendar())[:2]] = n
    today = now.replace(tzinfo=None).date()
    keep.update(n for day, n in by_day.items() if (today - day).days < s.backup_keep_daily)
    keep.update(by_week[w] for w in sorted(by_week, reverse=True)[: s.backup_keep_weekly])
    return keep


def prune() -> int:
    """Thin out old snapshots and remove files no kept snapshot needs. Only RecallSpring's own snapshot folders
    and content-addressed files are ever removed. Returns the number of snapshots removed."""
    root = backup_root()
    existing = snapshots()
    keep = keep_names([p.name for p in existing], clock.now())
    removed = 0
    for p in existing:
        if p.name not in keep:
            shutil.rmtree(p)
            removed += 1
    stale = clock.now().replace(tzinfo=None) - timedelta(days=1)
    snap_root = root / "snapshots"
    for p in snap_root.glob(".partial-*") if snap_root.is_dir() else []:
        stamp = p.name.removeprefix(".partial-")
        if SNAPSHOT_RE.match(stamp) and datetime.strptime(stamp, STAMP) < stale:
            shutil.rmtree(p, ignore_errors=True)
    needed: set[str] = set()
    for p in snapshots():
        try:
            needed.update(json.loads((p / "manifest.json").read_text(encoding="utf-8"))["files"]["keys"])
        except (OSError, ValueError, KeyError, TypeError):
            log.warning("backup %s has no readable manifest; keeping every file", p.name)
            return removed
    files_dir = root / "files"
    if files_dir.is_dir():
        for f in files_dir.rglob("*"):
            if f.is_file() and KEY_RE.match(key := f.relative_to(files_dir).as_posix()) and key not in needed:
                f.unlink()
    return removed


# ---------------------------------------------------------------- schedule


def due(now: datetime | None = None) -> bool:
    s = get_settings()
    if not s.backup_enabled:
        return False
    now = now or clock.now()
    st = read_status()
    last_success = _parse(st.get("last_success_at"))
    if last_success and now - last_success < timedelta(hours=s.backup_interval_hours):
        return False
    if _failed_last(st):
        failed_at = _parse(st["last_error"].get("at"))
        if failed_at and now - failed_at < RETRY_AFTER_FAILURE:
            return False
    return True


def run_if_due() -> bool:
    """Called by the worker. Never raises: a failure is recorded and retried after an hour."""
    if not due():
        return False
    try:
        run("scheduled")
    except BackupError:
        pass
    except Exception:  # noqa: BLE001 - the worker must keep processing jobs
        log.exception("scheduled backup crashed")
    return True


# ---------------------------------------------------------------- restore


def resolve(snapshot: str) -> Path:
    found = snapshots()
    if snapshot == "latest":
        if not found:
            raise BackupError("no_snapshot", f"There is no backup in {backup_root()} yet.")
        return found[-1]
    for p in found:
        if p.name == snapshot:
            return p
    raise BackupError("no_snapshot", f"No backup called {snapshot} in {backup_root()}.")


def restore(snapshot: str, database: str, storage: Path | None = None) -> dict[str, Any]:
    """Restore a snapshot into a NEW database (and optionally an empty storage folder). Never overwrites: refuses
    the database RecallSpring uses, any existing database and a non-empty folder."""
    if not NAME_RE.match(database) or len(database) > 63:
        raise BackupError("invalid_name", "Use a new database name of lowercase letters, digits and underscores.")
    url = _db_url()
    if database in (url.database, "postgres", "template0", "template1") or database.endswith(CHECK_SUFFIX):
        raise BackupError("would_overwrite", f"{database} cannot be used; choose a new name.")
    if storage is not None:
        if storage.resolve() == get_settings().storage_dir.resolve():
            raise BackupError("would_overwrite", "That is the storage folder RecallSpring uses now; choose a new one.")
        if storage.exists() and (not storage.is_dir() or any(storage.iterdir())):
            raise BackupError("would_overwrite", f"{storage} is not an empty folder; choose an empty or new one.")
    tools = find_tools()
    if tools is None:
        raise BackupError("no_pg_dump", "pg_restore was not found (not on PATH and RS_BACKUP_PG_BIN is not set).")
    folder = resolve(snapshot)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    admin = _admin_engine(url)
    try:
        with admin.connect() as conn:
            if conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": database}).first():
                raise BackupError("would_overwrite", f"The database {database} already exists; choose a new name.")
            conn.execute(text(f'CREATE DATABASE "{database}"'))
        try:
            _run(
                "pg_restore",
                [*tools.pg_restore, *tools.args(url, database), "--no-owner", "--exit-on-error"],
                env=tools.env(url),
                stdin=folder / "db.dump",
            )
        except BackupError:
            with admin.connect() as conn:  # created a moment ago by this call; nothing else uses it
                conn.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
            raise
    finally:
        admin.dispose()
    restored = _restored_counts(url, database)
    different = sorted(t for t, n in manifest["counts"].items() if restored.get(t) != n)
    files = 0
    if storage is not None:
        storage.mkdir(parents=True, exist_ok=True)
        for key in manifest["files"]["keys"]:
            src = backup_root() / "files" / key
            if KEY_RE.match(key) and src.is_file():
                _copy_verified(src, storage / key, key.rsplit("/", 1)[1])
                files += 1
    return {
        "snapshot": folder.name,
        "database": database,
        "database_url": url.set(database=database).render_as_string(hide_password=True),
        "rows": sum(restored.values()),
        "tables_differing": different,
        "files": files,
        "files_expected": manifest["files"]["count"],
        "storage": str(storage) if storage else None,
        "alembic_version": manifest.get("alembic_version"),
    }
