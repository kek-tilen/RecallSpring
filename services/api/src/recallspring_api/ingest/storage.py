"""Private, content-addressed storage for original source files.

Paths are built only from the owner's UUID and a SHA-256 hex digest, never from user-supplied filenames, so
path traversal is impossible by construction. Files are written atomically and never modified afterwards.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import unicodedata
import uuid
from pathlib import Path
from typing import BinaryIO

from ..config import get_settings

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_KEY = re.compile(r"^[0-9a-f-]{36}/[0-9a-f]{2}/[0-9a-f]{64}$")
CHUNK = 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".pdf": ("pdf", "application/pdf"),
    ".md": ("markdown", "text/markdown"),
    ".markdown": ("markdown", "text/markdown"),
    ".txt": ("text", "text/plain"),
}


class StorageError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _root() -> Path:
    return get_settings().storage_dir


def storage_key(user_id: uuid.UUID, sha256: str) -> str:
    if not _HEX64.match(sha256):
        raise ValueError("invalid digest")
    return f"{user_id}/{sha256[:2]}/{sha256}"


def blob_path(key: str) -> Path:
    if not _KEY.match(key):
        raise ValueError("invalid storage key")
    root = _root().resolve()
    path = (root / key).resolve()
    if root not in path.parents:
        raise ValueError("storage key escapes the storage root")
    return path


def spool(stream: BinaryIO, max_bytes: int) -> tuple[Path, str, int]:
    """Copy an upload to a private temp file, enforcing the size limit while hashing."""
    tmp_dir = _root() / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    size = 0
    fd, name = tempfile.mkstemp(dir=tmp_dir, prefix="upload-")
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := stream.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise StorageError("file_too_large")
                digest.update(chunk)
                out.write(chunk)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name), digest.hexdigest(), size


def spool_bytes(data: bytes) -> tuple[Path, str, int]:
    import io

    return spool(io.BytesIO(data), len(data))


def commit_blob(tmp: Path, key: str) -> None:
    dest = blob_path(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():  # identical content already stored (same user, same hash)
        tmp.unlink(missing_ok=True)
        return
    os.replace(tmp, dest)
    try:
        os.chmod(dest, 0o600)
    except OSError:  # pragma: no cover - Windows keeps the user-profile ACL
        pass


def sanitize_filename(name: str | None) -> str:
    base = (name or "").replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in unicodedata.normalize("NFC", base) if unicodedata.category(ch)[0] != "C")
    base = base.strip().strip(".") or "document"
    return base[:255]


def sniff(head: bytes, filename: str) -> tuple[str, str]:
    """Return (kind, mime) after checking the extension allowlist against the actual content."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise StorageError("unsupported_file_type")
    kind, mime = ALLOWED_EXTENSIONS[ext]
    is_pdf = head.startswith(b"%PDF-")
    if kind == "pdf" and not is_pdf:
        raise StorageError("content_does_not_match_type")
    if kind != "pdf" and is_pdf:
        raise StorageError("content_does_not_match_type")
    return kind, mime


def check_text_encoding(path: Path) -> None:
    from .extract import decode_text

    try:
        decode_text(path.read_bytes())
    except UnicodeDecodeError as exc:
        raise StorageError("unsupported_encoding") from exc
