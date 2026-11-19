"""Local owner authentication: Argon2id passwords, opaque session cookies and CSRF double-submit tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuthSession, User

SESSION_COOKIE = "rs_session"
CSRF_COOKIE = "rs_csrf"
CSRF_HEADER = "X-CSRF-Token"

_hasher = PasswordHasher()  # argon2-cffi defaults: Argon2id
_DUMMY_HASH = _hasher.hash("recallspring-dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def constant_time_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def create_session(db: Session, user: User, ttl_hours: int) -> tuple[str, str, AuthSession]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    row = AuthSession(
        user_id=user.id,
        token_hash=sha256_hex(token),
        csrf_hash=sha256_hex(csrf),
        expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
    )
    db.add(row)
    return token, csrf, row


def find_active_session(db: Session, token: str) -> AuthSession | None:
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == sha256_hex(token)))
    if row is None or row.revoked_at is not None or row.expires_at <= datetime.now(UTC):
        return None
    return row


class LoginRateLimiter:
    """In-process sliding-window limiter for failed logins (single API worker; see ADR-001)."""

    def __init__(self, max_failures: int, window_seconds: int) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque[float]:
        q = self._failures[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._trim(key, time.monotonic())) >= self.max_failures

    def record_failure(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._trim(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
