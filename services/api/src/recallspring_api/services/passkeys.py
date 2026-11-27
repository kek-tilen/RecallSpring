"""Passkeys (WebAuthn) alongside the password (decided 2026-11-27; docs/08 -> Passkeys).

Checked on the server with py_webauthn. Discoverable credentials with user verification required. A passkey belongs to
one address (its relying party): ``localhost`` (or ``<name>.localhost``) on this computer, and the host of
``RS_REMOTE_URL`` when set; other origins are refused. Challenges are random, single use and expire after 5 minutes;
they are kept in this process (one API worker, ADR-001), so a restart only means trying again.

Nothing secret is stored: the public key, the counter and what the browser reports. Audits never carry a credential
id or a key, only the passkey's own row id and name.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import parse_authentication_credential_json, parse_registration_credential_json
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from .. import clock
from ..config import get_settings
from ..errors import ApiError
from ..models import AuthSession, Passkey, User

RP_NAME = "RecallSpring"
CHALLENGE_SECONDS = 300
CONFIRM_SECONDS = 300
MAX_PASSKEYS = 20
MAX_CREDENTIAL_BYTES = 64 * 1024

# Authenticators that say what they are (AAGUID), for the suggested name. Unknown ones get "Passkey <date>".
# Source: the community list passkey-authenticator-aaguids (only well-known entries).
KNOWN_AAGUIDS = {
    "08987058-cadc-4b81-b6e1-30de50dcbe96": "Windows Hello",
    "9ddd1817-af5a-4672-a2b9-3e3dd95000a9": "Windows Hello",
    "6028b017-b1d4-4c02-b4b3-afcdafc96bb2": "Windows Hello",
    "fbfc3007-154e-4ecc-8c0b-6e020557d7bd": "iCloud Keychain",
    "ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4": "Google Password Manager",
    "adce0002-35bc-c60a-648b-0b25f1f05503": "Chrome on Mac",
    "bada5566-a7aa-401f-bd96-45619a55120d": "1Password",
    "d548826e-79b4-db40-a3d8-11116f7e8349": "Bitwarden",
    "531126d6-e717-415c-9320-3d9aa6981239": "Dashlane",
}


# ---------------------------------------------------------------- addresses


@dataclass(frozen=True)
class Party:
    rp_id: str
    origin: str


def party(origin: str | None) -> Party | None:
    """The relying party for a request's ``Origin``, or None where passkeys do not work (e.g. 127.0.0.1)."""
    if not origin:
        return None
    parts = urlsplit(origin.strip())
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or parts.path not in ("", "/") or not host:
        return None
    if host == "localhost" or host.endswith(".localhost"):
        return Party(host, f"{parts.scheme}://{parts.netloc.lower()}")
    remote = get_settings().remote_url
    if remote:
        r = urlsplit(remote)
        if (r.scheme, (r.netloc or "").lower()) == (parts.scheme, parts.netloc.lower()) and r.hostname:
            return Party(r.hostname.lower(), f"{r.scheme}://{r.netloc.lower()}")
    return None


def require_party(origin: str | None) -> Party:
    found = party(origin)
    if found is None:
        raise ApiError(
            400,
            "passkey_not_here",
            "Passkeys work at localhost (or the address in RS_REMOTE_URL), not at this address.",
        )
    return found


# ---------------------------------------------------------------- challenges


@dataclass
class Challenge:
    purpose: str  # "login" | "register" | "confirm"
    value: bytes
    party: Party
    user_id: uuid.UUID | None
    session_id: uuid.UUID | None
    expires: float


class ChallengeStore:
    """Single-use challenges in this process; expired ones are dropped as new ones arrive."""

    def __init__(self, limit: int = 1000) -> None:
        self._items: dict[str, Challenge] = {}
        self._lock = threading.Lock()
        self._limit = limit

    def put(self, challenge: Challenge) -> str:
        key = secrets.token_urlsafe(24)
        with self._lock:
            now = time.monotonic()
            for k in [k for k, c in self._items.items() if c.expires <= now]:
                del self._items[k]
            if len(self._items) >= self._limit:
                raise ApiError(429, "too_many_attempts", "Too many passkey attempts at once. Try again in a minute.")
            self._items[key] = challenge
        return key

    def take(self, key: str, purpose: str) -> Challenge:
        with self._lock:
            found = self._items.pop(key, None)
        if found is None or found.purpose != purpose or found.expires <= time.monotonic():
            raise ApiError(400, "passkey_expired", "That passkey prompt expired. Try again.")
        return found


STORE = ChallengeStore()


def _new_challenge(purpose: str, where: Party, user: User | None = None, session: AuthSession | None = None):
    value = secrets.token_bytes(32)
    key = STORE.put(
        Challenge(
            purpose,
            value,
            where,
            user.id if user else None,
            session.id if session else None,
            time.monotonic() + CHALLENGE_SECONDS,
        )
    )
    return key, value


def _check_origin(ch: Challenge, origin: str | None) -> None:
    if party(origin) != ch.party:
        raise ApiError(400, "passkey_not_here", "The passkey prompt was opened at another address.")


def _size_check(credential: dict[str, Any]) -> None:
    if len(json.dumps(credential)) > MAX_CREDENTIAL_BYTES:
        raise ApiError(413, "payload_too_large", "The passkey response is too large.")


# ---------------------------------------------------------------- views


def _sign_ins(db: Session, user: User) -> list[Passkey]:
    return list(db.scalars(select(Passkey).where(Passkey.user_id == user.id).order_by(Passkey.created_at)))


def item(p: Passkey) -> dict[str, Any]:
    return {
        "id": str(p.id),
        "name": p.name,
        "address": p.rp_id,
        "synced": p.backed_up,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "last_used_at": p.last_used_at.isoformat() if p.last_used_at else None,
    }


def view(db: Session, user: User, session: AuthSession | None) -> dict[str, Any]:
    """Settings › Sign-in: the password row, the passkeys, and whether this session is confirmed."""
    remote = get_settings().remote_url
    until = (
        (session.confirmed_at + timedelta(seconds=CONFIRM_SECONDS)).isoformat()
        if session is not None and session.confirmed_at and confirmed(session)
        else None
    )
    return {
        "remote_host": urlsplit(remote).hostname if remote else None,
        "password_changed_at": (user.password_changed_at or user.created_at).isoformat(),
        "password_changed": user.password_changed_at is not None,
        "passkeys": [item(p) for p in _sign_ins(db, user)],
        "confirmed_until": until,
    }


def suggested_name(aaguid: str | None, today: datetime) -> str:
    return KNOWN_AAGUIDS.get((aaguid or "").lower()) or f"Passkey {today.day} {today:%b %Y}"


# ---------------------------------------------------------------- confirm it is you


def confirmed(session: AuthSession | None) -> bool:
    return bool(
        session and session.confirmed_at and clock.now() - session.confirmed_at < timedelta(seconds=CONFIRM_SECONDS)
    )


def require_confirmed(session: AuthSession | None) -> None:
    if not confirmed(session):
        raise ApiError(403, "confirm_required", "Confirm it is you first (password or passkey).")


# ---------------------------------------------------------------- adding


def registration_options(db: Session, user: User, session: AuthSession, origin: str | None) -> dict[str, Any]:
    where = require_party(origin)
    existing = _sign_ins(db, user)
    if len(existing) >= MAX_PASSKEYS:
        raise ApiError(409, "too_many_passkeys", f"At most {MAX_PASSKEYS} passkeys. Remove one first.")
    key, value = _new_challenge("register", where, user, session)
    options = generate_registration_options(
        rp_id=where.rp_id,
        rp_name=RP_NAME,
        user_name=user.username,
        user_id=user.id.bytes,
        user_display_name=user.username,
        challenge=value,
        timeout=CHALLENGE_SECONDS * 1000,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=p.credential_id) for p in existing if p.rp_id == where.rp_id
        ],
    )
    return {"challenge_id": key, "options": json.loads(options_to_json(options))}


def register(
    db: Session, user: User, session: AuthSession, origin: str | None, challenge_id: str, credential: dict[str, Any]
) -> Passkey:
    _size_check(credential)
    ch = STORE.take(challenge_id, "register")
    if ch.user_id != user.id or ch.session_id != session.id:
        raise ApiError(400, "passkey_expired", "That passkey prompt expired. Try again.")
    _check_origin(ch, origin)
    try:
        parsed = parse_registration_credential_json(credential)
        verified = verify_registration_response(
            credential=parsed,
            expected_challenge=ch.value,
            expected_rp_id=ch.party.rp_id,
            expected_origin=ch.party.origin,
            require_user_verification=True,
        )
    except WebAuthnException as exc:
        raise ApiError(400, "passkey_invalid", "The browser's passkey could not be checked. Try again.") from exc
    if db.scalar(select(Passkey.id).where(Passkey.credential_id == verified.credential_id)):
        raise ApiError(409, "passkey_exists", "This passkey is already added.")
    transports = [t.value if hasattr(t, "value") else str(t) for t in (parsed.response.transports or [])]
    row = Passkey(
        user_id=user.id,
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        transports=transports[:8],
        backed_up=bool(verified.credential_backed_up),
        aaguid=(verified.aaguid or None),
        name=suggested_name(verified.aaguid, clock.now()),
        rp_id=ch.party.rp_id,
    )
    db.add(row)
    db.flush()
    return row


# ---------------------------------------------------------------- signing in and confirming


def authentication_options(
    origin: str | None,
    purpose: str,
    db: Session | None = None,
    user: User | None = None,
    session: AuthSession | None = None,
) -> dict[str, Any]:
    """``login``: any passkey for this address (discoverable). ``confirm``: only the signed-in learner's."""
    where = require_party(origin)
    allow = None
    if purpose == "confirm":
        assert db is not None and user is not None
        mine = [p for p in _sign_ins(db, user) if p.rp_id == where.rp_id]
        if not mine:
            raise ApiError(409, "no_passkey_here", f"No passkey for {where.rp_id} yet. Use the password.")
        allow = [PublicKeyCredentialDescriptor(id=p.credential_id) for p in mine]
    key, value = _new_challenge(purpose, where, user, session)
    options = generate_authentication_options(
        rp_id=where.rp_id,
        challenge=value,
        timeout=CHALLENGE_SECONDS * 1000,
        allow_credentials=allow,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return {"challenge_id": key, "options": json.loads(options_to_json(options))}


def authenticate(
    db: Session,
    origin: str | None,
    purpose: str,
    challenge_id: str,
    credential: dict[str, Any],
    session: AuthSession | None = None,
) -> Passkey:
    """Check an assertion and return its passkey (counter and last use updated). Raises ``passkey_failed``."""
    _size_check(credential)
    ch = STORE.take(challenge_id, purpose)
    _check_origin(ch, origin)
    if purpose == "confirm" and (session is None or ch.session_id != session.id):
        raise ApiError(400, "passkey_expired", "That passkey prompt expired. Try again.")
    failed = ApiError(401, "passkey_failed", "That passkey did not work here. Try again or use the password.")
    try:
        parsed = parse_authentication_credential_json(credential)
    except WebAuthnException as exc:
        raise failed from exc
    row = db.scalar(select(Passkey).where(Passkey.credential_id == parsed.raw_id))
    if row is None or row.rp_id != ch.party.rp_id:
        raise failed
    if purpose == "confirm" and row.user_id != ch.user_id:
        raise failed
    handle = parsed.response.user_handle
    if handle and handle != row.user_id.bytes:
        raise failed
    try:
        verified = verify_authentication_response(
            credential=parsed,
            expected_challenge=ch.value,
            expected_rp_id=ch.party.rp_id,
            expected_origin=ch.party.origin,
            credential_public_key=row.public_key,
            credential_current_sign_count=row.sign_count,
            require_user_verification=True,
        )
    except WebAuthnException as exc:
        raise failed from exc
    row.sign_count = verified.new_sign_count
    row.backed_up = bool(verified.credential_backed_up)
    row.last_used_at = clock.now()
    return row


def find(db: Session, user: User, passkey_id: uuid.UUID) -> Passkey:
    row = db.get(Passkey, passkey_id)
    if row is None or row.user_id != user.id:
        raise ApiError(404, "not_found", "That passkey is not there any more.")
    return row
