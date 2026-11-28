"""The one-time setup link for the first account (Docker install, 2026-11-28; docs/install-docker.md).

Normally the first account can be created only from the computer RecallSpring runs on: the API checks that the
browser comes from 127.0.0.1. Inside Docker every browser seems to come from Docker's own network, so that check
cannot tell. The installer (or ``recallspring setup-link``) makes a code instead and prints a link with it after
``#``, so the code never reaches a server log or another site; the page sends it with the sign-up.

Only a SHA-256 of the code is kept, in ``secrets_dir/setup-link.json`` (readable by its owner only). A code works
once, for a limited time, and only while no account exists; making a new one replaces the old one.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from . import clock
from .config import get_settings

# Crockford's Base32 without I, L, O and U: nothing to misread when typed from a terminal.
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
GROUPS = 3
GROUP_LEN = 4  # 12 characters, 60 bits; wrong codes are limited like failed sign-ins
DEFAULT_HOURS = 24
MAX_CODE_CHARS = 32


def _path() -> Path:
    return get_settings().secrets_dir / "setup-link.json"


def _digest(code: str) -> str:
    return hashlib.sha256(normalise(code).encode()).hexdigest()


def normalise(code: str) -> str:
    """Upper case, without dashes or spaces, and the letters people confuse with digits mapped as Crockford does."""
    plain = "".join(code.split()).replace("-", "").upper()
    return plain.translate(str.maketrans({"O": "0", "I": "1", "L": "1"}))


def issue(hours: int = DEFAULT_HOURS) -> tuple[str, datetime]:
    """Make a new code (replacing any earlier one) and return it with its expiry. The code itself is not kept."""
    raw = "".join(secrets.choice(ALPHABET) for _ in range(GROUPS * GROUP_LEN))
    code = "-".join(raw[i : i + GROUP_LEN] for i in range(0, len(raw), GROUP_LEN))
    expires = clock.now() + timedelta(hours=hours)
    folder = _path().parent
    folder.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(folder, 0o700)
    except OSError:  # pragma: no cover - Windows keeps the user-profile ACL
        pass
    data = json.dumps({"sha256": _digest(code), "expires_at": expires.isoformat()}).encode()
    tmp = folder / f".setup-link.{uuid.uuid4().hex}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, _path())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return code, expires


def _read() -> dict[str, str] | None:
    try:
        value = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or not isinstance(value.get("sha256"), str):
        return None
    try:
        if datetime.fromisoformat(str(value.get("expires_at"))) <= clock.now():
            return None
    except ValueError:
        return None
    return value


def pending() -> bool:
    """Whether a code that has not expired exists (the page then asks for the setup link)."""
    return _read() is not None


def valid(code: str | None) -> bool:
    if not code or len(code) > MAX_CODE_CHARS:
        return False
    value = _read()
    return value is not None and hmac.compare_digest(value["sha256"], _digest(code))


def clear() -> None:
    """After the first account exists the code is spent."""
    _path().unlink(missing_ok=True)
