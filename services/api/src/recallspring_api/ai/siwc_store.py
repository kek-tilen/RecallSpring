"""Protected local storage for Sign in with ChatGPT credentials (docs/04, docs/08 -> ChatGPT sign-in).

The OpenAI terms require tokens to stay "local and under the user's control". They are kept in ``secrets_dir``
(default ``local-data/secrets``, ignored by Git), never in the database, so they are not part of backups, never in the
browser and never in logs. On Windows each file is encrypted with DPAPI for the signed-in Windows user; elsewhere
the file is readable by its owner only (0600), as the official guide describes.

Files: ``chatgpt-host.json`` holds this computer's ``ext_agent_host_id`` (an identifier, not a secret, and not
user-identifying); ``chatgpt-<user id>.bin`` holds one learner's record (issued client id, account, scopes, tokens).
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from ..config import get_settings

DPAPI_MAGIC = b"RSDPAPI1\n"
PLAIN_MAGIC = b"RSPLAIN1\n"
_ENTROPY = b"RecallSpring ChatGPT sign-in"


def _dir() -> Path:
    path = get_settings().secrets_dir
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:  # pragma: no cover - Windows keeps the user-profile ACL
        pass
    return path


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover
        pass


# --- Windows DPAPI (CryptProtectData), bound to the Windows user account --------------------------------------------


def _dpapi(data: bytes, protect: bool) -> bytes:  # pragma: no cover - exercised on Windows only
    import ctypes
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob(value: bytes) -> tuple[Blob, Any]:
        buf = ctypes.create_string_buffer(value, len(value))
        return Blob(len(value), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    data_in, keep_in = blob(data)
    entropy, keep_entropy = blob(_ENTROPY)
    out = Blob()
    flags = 0x1  # CRYPTPROTECT_UI_FORBIDDEN
    if protect:
        ok = crypt32.CryptProtectData(
            ctypes.byref(data_in), "RecallSpring", ctypes.byref(entropy), None, None, flags, ctypes.byref(out)
        )
    else:
        ok = crypt32.CryptUnprotectData(
            ctypes.byref(data_in), None, ctypes.byref(entropy), None, None, flags, ctypes.byref(out)
        )
    del keep_in, keep_entropy
    if not ok:
        raise OSError(ctypes.get_last_error(), "Windows could not protect the ChatGPT credentials")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out.pbData, ctypes.c_void_p))


def _seal(data: bytes) -> bytes:
    if os.name == "nt":
        return DPAPI_MAGIC + _dpapi(data, protect=True)
    return PLAIN_MAGIC + data


def _open(raw: bytes) -> bytes:
    if raw.startswith(DPAPI_MAGIC):
        return _dpapi(raw[len(DPAPI_MAGIC) :], protect=False)
    if raw.startswith(PLAIN_MAGIC):
        return raw[len(PLAIN_MAGIC) :]
    raise ValueError("unknown credential file format")


# --- public -----------------------------------------------------------------------------------------------------------


def host_id() -> str:
    """This computer's ``ext_agent_host_id`` (urn:uuid, created once and kept)."""
    path = _dir() / "chatgpt-host.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))["ext_agent_host_id"]
        if isinstance(value, str) and value.startswith("urn:uuid:"):
            return value
    except (OSError, ValueError, KeyError):
        pass
    value = f"urn:uuid:{uuid.uuid4()}"
    _write_atomic(path, json.dumps({"ext_agent_host_id": value}).encode("utf-8"))
    return value


def _record_path(user_id: uuid.UUID) -> Path:
    return _dir() / f"chatgpt-{user_id}.bin"


def load(user_id: uuid.UUID) -> dict[str, Any]:
    path = _record_path(user_id)
    try:
        return json.loads(_open(path.read_bytes()))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        # Unreadable (e.g. copied from another Windows account): treat as signed out; signing in again replaces it.
        return {"unreadable": True}


def save(user_id: uuid.UUID, record: dict[str, Any]) -> None:
    _write_atomic(_record_path(user_id), _seal(json.dumps(record).encode("utf-8")))


def forget_tokens(user_id: uuid.UUID) -> dict[str, Any]:
    """Remove the tokens but keep the issued client id, so the next sign-in is a returning one."""
    record = load(user_id)
    kept = {k: record[k] for k in ("client_id", "email") if k in record}
    if kept:
        save(user_id, kept)
    else:
        _record_path(user_id).unlink(missing_ok=True)
    return kept
