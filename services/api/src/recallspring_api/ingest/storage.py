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
from .formats import CODE_LANGUAGES

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_KEY = re.compile(r"^[0-9a-f-]{36}/[0-9a-f]{2}/[0-9a-f]{64}$")
CHUNK = 1024 * 1024

ALLOWED_EXTENSIONS = {
    ".pdf": ("pdf", "application/pdf"),
    ".md": ("markdown", "text/markdown"),
    ".markdown": ("markdown", "text/markdown"),
    ".txt": ("text", "text/plain"),
    # Photos of handwritten notes, notebooks and exercises. SVG is deliberately not allowed (it can carry script).
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".webp": ("image", "image/webp"),
    # Office Open XML. Only the text is read (office.py); macros, embedded objects and links are never run.
    ".docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".pptx": ("pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"),
    ".ppsx": ("pptx", "application/vnd.openxmlformats-officedocument.presentationml.slideshow"),
    ".xlsx": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    # OpenDocument (LibreOffice, OpenOffice, Google Docs exports), read like Office files (odf.py).
    ".odt": ("odt", "application/vnd.oasis.opendocument.text"),
    ".odp": ("odp", "application/vnd.oasis.opendocument.presentation"),
    ".ods": ("ods", "application/vnd.oasis.opendocument.spreadsheet"),
    # Text formats (formats.py): tables, lecture subtitles/transcripts, notebooks and LaTeX. Never executed.
    ".csv": ("csv", "text/csv"),
    ".tsv": ("csv", "text/tab-separated-values"),
    ".srt": ("subtitles", "application/x-subrip"),
    ".vtt": ("subtitles", "text/vtt"),
    ".ipynb": ("notebook", "application/x-ipynb+json"),
    ".tex": ("latex", "application/x-tex"),
    # Source code: kept as text with its language, never run.
    **{ext: ("code", "text/plain") for ext in CODE_LANGUAGES},
}
OFFICE_KINDS = {"docx", "pptx", "xlsx"}
ODF_KINDS = {"odt", "odp", "ods"}
PACKAGE_KINDS = OFFICE_KINDS | ODF_KINDS  # ZIP packages
LENIENT_TEXT_KINDS = {"csv", "subtitles"}  # Windows-1250 is accepted (and reported) when not UTF-8
# Old binary formats, macro-enabled files and templates: refused with a "save it as .docx/.pptx/.xlsx" hint.
UNSUPPORTED_OFFICE = {".doc", ".ppt", ".pps", ".xls", ".docm", ".pptm", ".xlsm", ".dotx", ".potx", ".xltx", ".rtf"}
ZIP_MAGIC = b"PK\x03\x04"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # password-protected Office files and the old formats

# Kinds whose files are plain text: they get the smaller text upload limit.
TEXT_KINDS = {"markdown", "text", "csv", "subtitles", "code", "latex"}


def upload_limit(filename: str) -> int:
    """The size limit for a file of this type (by extension; the content is checked after upload)."""
    settings = get_settings()
    kind = ALLOWED_EXTENSIONS.get(Path(filename).suffix.lower(), ("", ""))[0]
    if kind in TEXT_KINDS:
        return settings.max_text_upload_bytes
    if kind == "image":
        return settings.max_image_upload_bytes
    return settings.max_upload_bytes


IMAGE_MAGIC = {
    "image/png": lambda h: h.startswith(b"\x89PNG\r\n\x1a\n"),
    "image/jpeg": lambda h: h.startswith(b"\xff\xd8\xff"),
    "image/webp": lambda h: h[:4] == b"RIFF" and h[8:12] == b"WEBP",
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
    if ext in UNSUPPORTED_OFFICE:
        raise StorageError("office_format_unsupported")
    if ext not in ALLOWED_EXTENSIONS:
        raise StorageError("unsupported_file_type")
    kind, mime = ALLOWED_EXTENSIONS[ext]
    if kind in PACKAGE_KINDS:
        if head.startswith(OLE_MAGIC):
            raise StorageError("office_protected")
        if not head.startswith(ZIP_MAGIC):
            raise StorageError("content_does_not_match_type")
        return kind, mime
    is_pdf = head.startswith(b"%PDF-")
    if kind == "pdf" and not is_pdf:
        raise StorageError("content_does_not_match_type")
    if kind != "pdf" and is_pdf:
        raise StorageError("content_does_not_match_type")
    if kind == "image" and not IMAGE_MAGIC[mime](head):
        raise StorageError("content_does_not_match_type")
    if kind == "notebook" and not head.lstrip(b"\xef\xbb\xbf \t\r\n").startswith(b"{"):
        raise StorageError("content_does_not_match_type")
    return kind, mime


def check_office_package(path: Path, kind: str) -> None:
    """A real, readable Office or OpenDocument package of the declared kind (reads only the package index)."""
    from . import odf
    from .office import PackageError, check_package

    passed_on = ("content_does_not_match_type", "document_too_large", "office_protected")
    try:
        if kind in ODF_KINDS:
            odf.check_package(path, kind)
        else:
            check_package(path, kind)
    except PackageError as exc:
        raise StorageError(exc.code if exc.code in passed_on else "office_unreadable") from exc


def check_text_encoding(path: Path, kind: str = "text") -> None:
    from .extract import decode_text
    from .formats import decode_lenient

    try:
        (decode_lenient if kind in LENIENT_TEXT_KINDS else decode_text)(path.read_bytes())
    except UnicodeDecodeError as exc:
        raise StorageError("unsupported_encoding") from exc
