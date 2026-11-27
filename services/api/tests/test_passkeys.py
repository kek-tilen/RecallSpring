"""Passkeys alongside the password, Change password and reset-password (docs/08 -> Passkeys)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from recallspring_api import cli
from recallspring_api.config import get_settings
from recallspring_api.db import new_session
from recallspring_api.main import create_app
from recallspring_api.models import AuditEvent, AuthSession, Passkey

from .conftest import PASSWORD, Api, FrozenClock, make_user
from .softkey import SoftKey

LOCAL = "http://localhost:4318"
NEW_PASSWORD = "a much newer passphrase"


def _post(api: Api, path: str, json: Any = None, origin: str = LOCAL) -> Any:
    return api.client.post(f"/api/v1{path}", json=json, headers={**api.headers(), "Origin": origin})


def _confirm(api: Api) -> None:
    assert _post(api, "/auth/confirm", {"password": PASSWORD}).status_code == 200


def _add(api: Api, key: SoftKey, origin: str = LOCAL) -> dict[str, Any]:
    opts = _post(api, "/auth/passkeys/options", origin=origin)
    assert opts.status_code == 200, opts.text
    body = opts.json()
    r = _post(
        api,
        "/auth/passkeys",
        {"challenge_id": body["challenge_id"], "credential": key.create(body["options"], origin)},
        origin,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _passkey_login(client: TestClient, key: SoftKey, origin: str = LOCAL) -> Any:
    opts = client.post("/api/v1/auth/passkey/login/options", headers={"Origin": origin})
    assert opts.status_code == 200, opts.text
    body = opts.json()
    return client.post(
        "/api/v1/auth/passkey/login",
        json={"challenge_id": body["challenge_id"], "credential": key.get(body["options"], origin)},
        headers={"Origin": origin},
    )


def _actions() -> list[AuditEvent]:
    with new_session() as db:
        return list(db.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at)))


def test_adding_needs_confirmation_and_records_only_public_data(owner_api: Api) -> None:
    refused = _post(owner_api, "/auth/passkeys/options")
    assert refused.status_code == 403 and refused.json()["code"] == "confirm_required"
    _confirm(owner_api)
    opts = _post(owner_api, "/auth/passkeys/options").json()["options"]
    assert opts["rp"]["id"] == "localhost"
    assert opts["authenticatorSelection"]["residentKey"] == "required"
    assert opts["authenticatorSelection"]["userVerification"] == "required"

    key = SoftKey()
    added = _add(owner_api, key)
    assert added["passkey"]["name"] == "Windows Hello"
    assert added["passkey"]["address"] == "localhost" and added["passkey"]["synced"] is False
    listed = owner_api.get("/auth/passkeys").json()
    assert [p["name"] for p in listed["passkeys"]] == ["Windows Hello"]
    assert listed["confirmed_until"] and listed["password_changed"] is False

    event = next(e for e in _actions() if e.action == "auth.passkey_added")
    assert event.details == {"name": "Windows Hello", "address": "localhost", "synced": False}
    with new_session() as db:
        row = db.scalar(select(Passkey))
        assert row is not None and row.credential_id == key.credential_id and row.transports == ["internal"]


def test_passkey_sign_in_is_single_use_and_audited(owner_api: Api, client: TestClient) -> None:
    _confirm(owner_api)
    key = SoftKey(synced=True)
    _add(owner_api, key)
    with TestClient(create_app()) as fresh:
        r = _passkey_login(fresh, key)
        assert r.status_code == 200, r.text
        assert r.json()["user"]["username"] == "owner"
        assert fresh.get("/api/v1/auth/session").status_code == 200

        opts = fresh.post("/api/v1/auth/passkey/login/options", headers={"Origin": LOCAL}).json()
        payload = {"challenge_id": opts["challenge_id"], "credential": key.get(opts["options"], LOCAL)}
        assert fresh.post("/api/v1/auth/passkey/login", json=payload, headers={"Origin": LOCAL}).status_code == 200
        again = fresh.post("/api/v1/auth/passkey/login", json=payload, headers={"Origin": LOCAL})
        assert again.status_code == 400 and again.json()["code"] == "passkey_expired"

    logins = [e for e in _actions() if e.action == "auth.login"]
    assert logins[-1].details == {"method": "passkey"}
    with new_session() as db:
        row = db.scalar(select(Passkey))
        assert row is not None and row.last_used_at is not None and row.sign_count == 2 and row.backed_up is True


def test_wrong_address_unknown_passkey_and_rate_limit(owner_api: Api, client: TestClient) -> None:
    ip = client.post("/api/v1/auth/passkey/login/options", headers={"Origin": "http://127.0.0.1:4318"})
    assert ip.status_code == 400 and ip.json()["code"] == "passkey_not_here"

    _confirm(owner_api)
    key = SoftKey()
    _add(owner_api, key)
    # a prompt opened at localhost cannot be answered from another address
    opts = client.post("/api/v1/auth/passkey/login/options", headers={"Origin": LOCAL}).json()
    other = "http://demo.localhost:4318"
    moved = client.post(
        "/api/v1/auth/passkey/login",
        json={"challenge_id": opts["challenge_id"], "credential": key.get(opts["options"], other)},
        headers={"Origin": other},
    )
    assert moved.status_code == 400 and moved.json()["code"] == "passkey_not_here"

    stranger = SoftKey(user_handle=b"someone-else")
    for _ in range(5):
        r = _passkey_login(client, stranger)
        assert r.status_code == 401 and r.json()["code"] == "passkey_failed"
    blocked = client.post("/api/v1/auth/passkey/login/options", headers={"Origin": LOCAL})
    assert blocked.status_code == 429
    assert sum(1 for e in _actions() if e.action == "auth.login_failed") == 5


def test_passkey_without_user_verification_is_refused(owner_api: Api) -> None:
    _confirm(owner_api)
    body = _post(owner_api, "/auth/passkeys/options").json()
    key = SoftKey(uv=False)
    r = _post(
        owner_api,
        "/auth/passkeys",
        {"challenge_id": body["challenge_id"], "credential": key.create(body["options"], LOCAL)},
    )
    assert r.status_code == 400 and r.json()["code"] == "passkey_invalid"


def test_confirmation_expires_and_a_passkey_can_confirm(owner_api: Api, frozen: FrozenClock) -> None:
    _confirm(owner_api)
    key = SoftKey()
    passkey_id = _add(owner_api, key)["passkey"]["id"]
    frozen.advance(minutes=6)
    refused = owner_api.client.delete(f"/api/v1/auth/passkeys/{passkey_id}", headers=owner_api.headers())
    assert refused.status_code == 403 and refused.json()["code"] == "confirm_required"

    opts = _post(owner_api, "/auth/confirm/passkey/options").json()
    assert [c["id"] for c in opts["options"]["allowCredentials"]]
    ok = _post(
        owner_api,
        "/auth/confirm/passkey",
        {"challenge_id": opts["challenge_id"], "credential": key.get(opts["options"], LOCAL)},
    )
    assert ok.status_code == 200 and ok.json()["confirmed_until"]

    removed = owner_api.client.delete(f"/api/v1/auth/passkeys/{passkey_id}", headers=owner_api.headers())
    assert removed.status_code == 200 and removed.json()["passkeys"] == []
    event = next(e for e in _actions() if e.action == "auth.passkey_removed")
    assert event.details == {"name": "Windows Hello", "address": "localhost"}
    with TestClient(create_app()) as fresh:
        assert _passkey_login(fresh, key).status_code == 401  # a removed passkey stops working at once


def test_rename_is_audited_and_limited_to_own_passkeys(owner_api: Api, client: TestClient) -> None:
    _confirm(owner_api)
    passkey_id = _add(owner_api, SoftKey())["passkey"]["id"]
    r = owner_api.patch(f"/auth/passkeys/{passkey_id}", {"name": "  Work   laptop "})
    assert r.status_code == 200 and r.json()["passkeys"][0]["name"] == "Work laptop"
    event = next(e for e in _actions() if e.action == "auth.passkey_renamed")
    assert event.details == {"from": "Windows Hello", "to": "Work laptop"}

    make_user("second")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        assert other.login("second").status_code == 200
        assert other.patch(f"/auth/passkeys/{passkey_id}", {"name": "mine"}).status_code == 404


def test_remote_address_is_its_own_relying_party(owner_api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "remote_url", "https://study.example.org")
    remote = "https://study.example.org"
    _confirm(owner_api)
    opts = _post(owner_api, "/auth/passkeys/options", origin=remote).json()["options"]
    assert opts["rp"]["id"] == "study.example.org"
    key = SoftKey()
    assert _add(owner_api, key, remote)["passkey"]["address"] == "study.example.org"
    assert owner_api.get("/auth/passkeys").json()["remote_host"] == "study.example.org"
    # the same passkey is not offered at localhost
    with TestClient(create_app()) as fresh:
        assert _passkey_login(fresh, key, LOCAL).status_code == 401
        assert _passkey_login(fresh, key, remote).status_code == 200


def test_change_password_signs_out_other_sessions(owner_api: Api, client: TestClient) -> None:
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        assert other.login("owner").status_code == 200
        wrong = owner_api.post("/auth/password", {"current_password": "not it at all", "new_password": NEW_PASSWORD})
        assert wrong.status_code == 401
        short = owner_api.post("/auth/password", {"current_password": PASSWORD, "new_password": "short"})
        assert short.status_code == 422
        ok = owner_api.post("/auth/password", {"current_password": PASSWORD, "new_password": NEW_PASSWORD})
        assert ok.status_code == 200 and ok.json()["password_changed"] is True
        assert owner_api.get("/auth/session").status_code == 200  # this browser stays signed in
        assert other.get("/auth/session").status_code == 401
    with TestClient(create_app()) as fresh:
        assert Api(fresh).login("owner").status_code == 401
        assert Api(fresh).login("owner", NEW_PASSWORD).status_code == 200
    event = next(e for e in _actions() if e.action == "auth.password_changed")
    assert event.details == {"signed_out": 1}


def test_reset_password_command_signs_out_every_session(owner_api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": NEW_PASSWORD)
    assert cli.main(["reset-password", "--username", "owner"]) == 0
    assert owner_api.get("/auth/session").status_code == 401
    with new_session() as db:
        assert all(s.revoked_at is not None for s in db.scalars(select(AuthSession)))
    event = next(e for e in _actions() if e.action == "auth.password_reset")
    assert event.details == {"via": "command", "signed_out": 1}
    assert cli.main(["reset-password", "--username", "nobody"]) == 1
