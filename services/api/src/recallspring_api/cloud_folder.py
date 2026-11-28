"""A synced folder for the cloud copy of backups (cloud.py) and for learners' own cloud folders (services/my_drive.py),
decided 2026-11-28.

iCloud Drive offers no way for a server to put files in it; what works is the folder its app keeps in sync. The same
holds for Proton Drive, Nextcloud, Syncthing, pCloud or a network drive, so this is one general provider: RecallSpring
writes into a folder on the computer it runs on, and the sync app (if any) uploads it.

- No sign-in, no token, no secret. The chosen folders are kept with the other backup settings
  (``backup_settings_file``: ``cloud`` for the cloud copy, ``drive_folder`` for learners), or come from the server
  settings (RS_CLOUD_FOLDER_DIR, RS_DRIVE_FOLDER_DIR) when ``backup_settings_from_web`` is off. Only the first account
  chooses them.
- Items are referred to by their path relative to the folder RecallSpring was given (``a/b/c``, never ``..``), so the
  same calls as Google Drive, Dropbox and OneDrive work. A rename returns the new reference.
- Every file is written as a hidden ``.part`` file and renamed when complete, so a sync app never uploads half a file;
  the size is read back.
- RecallSpring makes only its own last folder inside one that exists. When the chosen folder is gone (the sync app
  signed out, a network drive not mounted) it never makes it again on the local disk: ``folder_missing``.
- RecallSpring sees only what it wrote; whether the sync app has uploaded it is not visible here.
"""

from __future__ import annotations

import errno
import os
import shutil
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import backup
from .cloud import CloudError
from .config import get_settings

CHUNK = 8 * 1024 * 1024
PART_PREFIX = ".recallspring-"  # temporary files while writing; never listed
LABEL = "synced folder"
DIRECT = {"Dropbox", "OneDrive", "Google Drive"}  # sync apps RecallSpring can also connect to directly

# Where sync apps usually keep their folder, under the home folder of the user RecallSpring runs as (a hint only).
_USUAL = (
    ("iCloud Drive", ("iCloudDrive",)),
    ("iCloud Drive", ("Library", "Mobile Documents", "com~apple~CloudDocs")),
    ("Dropbox", ("Dropbox",)),
    ("OneDrive", ("OneDrive",)),
    ("Google Drive", ("Google Drive",)),
    ("Nextcloud", ("Nextcloud",)),
    ("Proton Drive", ("Proton Drive",)),
    ("pCloud", ("pCloud Drive",)),
)


# ---------------------------------------------------------------- the chosen folders


def from_web() -> bool:
    """Whether the folders may be chosen in Settings (backup.folders_from_web); else RS_CLOUD_FOLDER_DIR and
    RS_DRIVE_FOLDER_DIR give them."""
    return backup.folders_from_web()


def drive_base() -> Path | None:
    """The folder learners' copies go under (each in a subfolder named by their sign-in name), or None."""
    if not from_web():
        value = get_settings().drive_folder_dir
        return Path(value) if value else None
    value = backup.read_config().get("drive_folder")
    return Path(value) if isinstance(value, str) and value and Path(value).is_absolute() else None


def app_of(path: Path) -> str | None:
    return backup.sync_provider(path)


def display(path: Path) -> str:
    """``iCloud Drive › RecallSpring backups`` when a sync app is recognised from the path, else the path itself."""
    app = app_of(path)
    if app is None:
        return str(path)
    parts = list(path.parts)
    for i in range(len(parts) - 1, -1, -1):
        if backup.sync_provider(Path(parts[i])) == app:
            rest = parts[i + 1 :]
            return " › ".join([app, *rest])
    return str(path)


def suggestions() -> list[dict[str, str]]:
    """Folders sync apps usually make that exist on this computer (for the first account to pick from)."""
    found: list[dict[str, str]] = []
    try:
        home = Path.home()
    except RuntimeError:
        return found
    seen: set[str] = set()
    for app, parts in _USUAL:
        candidates = [home.joinpath(*parts)]
        if app == "OneDrive":  # OneDrive for work or school: "OneDrive - <organisation>"
            try:
                candidates += sorted(p for p in home.glob("OneDrive - *") if p.is_dir())
            except OSError:
                pass
        for p in candidates:
            try:
                ok = p.is_dir()
            except OSError:
                ok = False
            if ok and str(p) not in seen:
                seen.add(str(p))
                found.append({"app": app, "path": str(p)})
    return found


# ---------------------------------------------------------------- checking a folder before it is used


def check(raw: str | None, kind: str) -> dict[str, Any]:
    """Try a folder for the cloud copy (``kind="copy"``) or for learners' copies (``"drive"``). Creates nothing.

    RecallSpring may make the last folder; the one above it must exist (so a missing sync folder or drive is never
    replaced by a folder on the local disk)."""
    checks: list[dict[str, str]] = []

    def add(check_id: str, level: str, message: str) -> None:
        checks.append({"id": check_id, "level": level, "text": message})

    def result(p: Path | None = None, **extra: Any) -> dict[str, Any]:
        return {"path": str(p) if p else None, "ok": all(c["level"] != "bad" for c in checks), "checks": checks} | extra

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
    if refusal := backup._place_refusal(p):
        add("place", "bad", refusal.replace("backups need", "this needs"))
        return result(p)
    local = backup.backup_root().resolve()
    if backup._inside(p, local) or backup._inside(local, p):
        add("place", "bad", "That is the backup folder or holds it; the copy needs a folder of its own.")
        return result(p)
    if p.exists() and not p.is_dir():
        add("place", "bad", "That is a file, not a folder.")
        return result(p)
    parent = p if p.exists() else p.parent
    if not parent.is_dir():
        add(
            "parent",
            "bad",
            f"The folder {parent} is not there. Is the sync app running and signed in, or the drive connected?",
        )
        return result(p)
    if not backup._writable(parent):
        add("write", "bad", "RecallSpring cannot write there. Check the folder may be written to.")
        return result(p)
    free = shutil.disk_usage(parent).free
    room = f"{free / backup.GIB:,.0f} GB free" if free >= backup.GIB else f"{free / 1024**2:,.0f} MB free"
    where = "RecallSpring can write here" if p.exists() else "RecallSpring can make this folder"
    add("write", "ok", f"{where} · {room} on this disk")
    app = app_of(p)
    if app is None:
        add(
            "sync",
            "warn",
            "No sync app recognised from the path. That is fine for Syncthing, a network drive or another app; "
            "RecallSpring only copies into the folder.",
        )
    else:
        direct = f". {app} can also connect directly, which checks every upload" if app in DIRECT else ""
        add("sync", "ok", f"{app}, recognised from the path{direct}")
    add(
        "upload",
        "warn",
        f"RecallSpring sees what it put in the folder, not when {app or 'the sync app'} has uploaded it.",
    )
    if kind == "drive":
        add("learners", "warn", "Learners who use it put their copy in the account this folder syncs to, not theirs.")
    return result(p, exists=p.exists(), free_bytes=free, sync=app, display=display(p))


def prepare(raw: str | None, kind: str) -> Path:
    """Check the folder and make its last part. CloudError ``folder_refused`` with the first refusal."""
    found = check(raw, kind)
    if not found["ok"]:
        bad = next(c["text"] for c in found["checks"] if c["level"] == "bad")
        raise CloudError("folder_refused", bad)
    p = Path(found["path"])
    try:
        p.mkdir(exist_ok=True)
    except OSError as exc:
        raise CloudError("folder_refused", f"RecallSpring could not make the folder {p}.") from exc
    return p


# ---------------------------------------------------------------- the provider


class Folder:
    """A folder on this computer behind the same calls as cloud.Google, cloud_dropbox.Dropbox and
    cloud_onedrive.OneDrive. References are paths relative to ``base``; ``base`` itself is never made."""

    name = "folder"

    def __init__(self, base: Path, *, backup_root: str = "", drive_root: str = "") -> None:
        self.base = base
        self.backup_root = backup_root  # the cloud copy's own folder, inside base
        self.drive_root = drive_root  # a learner's own folder, inside base
        app = app_of(base / (backup_root or drive_root or "."))
        self.label = app or LABEL
        self.where = display(base)

    # -- tokens: none

    def access_token(self, http: Any, token_file: Any = None) -> str:
        return ""

    def revoke(self, http: Any, token_file: Any) -> None:
        return None

    # -- paths

    def _gone(self) -> CloudError:
        app = app_of(self.base) or "the sync app"
        return CloudError(
            "folder_missing",
            f"The folder {self.base} is not there. Is {app} running and signed in, or the drive connected? "
            "RecallSpring tries again later.",
        )

    def _abs(self, ref: str | None) -> Path:
        if not self.base.is_dir():
            raise self._gone()
        if not ref:
            return self.base
        parts = ref.split("/")
        if any(x in ("", ".", "..") for x in parts):
            raise CloudError("missing", "That item is not in the folder.")
        return self.base.joinpath(*parts)

    @staticmethod
    def _ref(parent: str | None, name: str) -> str:
        return f"{parent}/{name}" if parent else name

    @contextmanager
    def _os(self) -> Iterator[None]:
        try:
            yield
        except CloudError:
            raise
        except FileNotFoundError as exc:
            if not self.base.is_dir():
                raise self._gone() from exc
            raise CloudError("missing", "A folder RecallSpring made is gone. RecallSpring makes it again.") from exc
        except OSError as exc:
            if exc.errno in (errno.ENOSPC, getattr(errno, "EDQUOT", -1)):
                raise CloudError(
                    "no_room", f"Not enough room on the disk of {self.where}. RecallSpring tries again tomorrow."
                ) from exc
            raise CloudError(
                "unreachable",
                f"RecallSpring could not write to {self.where} ({type(exc).__name__}). It tries again later.",
            ) from exc

    def _free_name(self, folder: Path, name: str, skip: Path | None = None) -> str:
        """``name``, or ``name (1)`` and so on when it is taken regardless of letter case."""
        taken = {c.name.lower() for c in folder.iterdir() if skip is None or c != skip}
        if name.lower() not in taken:
            return name
        stem, dot, ext = name.rpartition(".")
        if not dot or not stem:
            stem, ext = name, ""
        for n in range(1, 1000):
            candidate = f"{stem} ({n}){'.' + ext if ext else ''}"
            if candidate.lower() not in taken:
                return candidate
        raise CloudError("conflict", f"Too many items named {name}.")

    # -- metadata

    def get(self, http: Any, token: str, ref: str) -> dict[str, Any] | None:
        p = self._abs(ref)
        if not p.exists():
            return None
        return {"id": ref, "name": p.name, "trashed": False}

    def children(self, http: Any, token: str, parent: str) -> dict[str, dict[str, Any]]:
        folder = self._abs(parent)
        if not folder.is_dir():
            raise CloudError("missing", "A folder RecallSpring made is gone. RecallSpring makes it again.")
        found: dict[str, dict[str, Any]] = {}
        with self._os():
            for c in folder.iterdir():
                if c.name.startswith(PART_PREFIX):
                    continue
                is_dir = c.is_dir()
                found[c.name] = {
                    "id": self._ref(parent, c.name),
                    "size": 0 if is_dir else c.stat().st_size,
                    "folder": is_dir,
                }
        return found

    def ensure_folder(self, http: Any, token: str, name: str, parent: str | None) -> str:
        p = self._abs(self._ref(parent, name))
        with self._os():
            if p.exists() and not p.is_dir():
                raise CloudError("conflict", f"A file named {name} is in the way in {self.where}.")
            p.mkdir(exist_ok=True)  # never its parents: a missing folder above is reported, not made
        return self._ref(parent, name)

    def new_folder(self, http: Any, token: str, name: str, parent: str) -> str:
        folder = self._abs(parent)
        with self._os():
            free = self._free_name(folder, name)
            (folder / free).mkdir()
        return self._ref(parent, free)

    def rename(self, http: Any, token: str, ref: str, name: str) -> str:
        """Returns the new reference (the caller updates what it keeps under the old one)."""
        p = self._abs(ref)
        if p.name == name:
            return ref
        with self._os():
            free = self._free_name(p.parent, name, skip=p)
            p.rename(p.with_name(free))
        parent, _, _ = ref.rpartition("/")
        return self._ref(parent or None, free)

    def delete(self, http: Any, token: str, ref: str) -> None:
        if not ref:
            raise CloudError("refused", "RecallSpring deletes only folders it made.")
        p = self._abs(ref)
        with self._os():
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()

    def free_bytes(self, http: Any, token: str) -> int | None:
        try:
            return shutil.disk_usage(self._abs(None)).free
        except OSError:
            return None

    # -- writing

    def upload(
        self,
        http: Any,
        token: str,
        path: Path,
        parent: str,
        on_bytes: Callable[[int], None],
        name: str | None = None,
        file_id: list[str] | None = None,
    ) -> int:
        """Copy as a hidden .part file, then rename it; a name that is taken gets a number. Returns the size on disk."""
        folder = self._abs(parent)
        if not folder.is_dir():
            raise CloudError("missing", "A folder RecallSpring made is gone. RecallSpring makes it again.")
        tmp = folder / f"{PART_PREFIX}{uuid.uuid4().hex}.part"
        try:
            with self._os():
                with path.open("rb") as src, tmp.open("wb") as dst:
                    while chunk := src.read(CHUNK):
                        dst.write(chunk)
                        on_bytes(len(chunk))
                    dst.flush()
                    os.fsync(dst.fileno())
                final = self._free_name(folder, name or path.name)
                os.replace(tmp, folder / final)
                size = (folder / final).stat().st_size
        finally:
            tmp.unlink(missing_ok=True)
        if file_id is not None:
            file_id.append(self._ref(parent, final))
        return size
