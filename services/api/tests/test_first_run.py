"""Installing for other people (plan-without-claude.md, Phase 3): the first-run page creates the first account only
on this computer, only while none exists, never from another site or in production; the learner can change their
time zone and the assistant they study with."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from recallspring_api.api import auth
from recallspring_api.config import get_settings
from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent, User

from .conftest import Api

FIRST = {"username": "ana.k", "password": "a long local password", "timezone": "America/New_York"}


@pytest.fixture
def local(monkeypatch: pytest.MonkeyPatch) -> None:
    """The test client calls itself "testclient"; count it as this computer."""
    monkeypatch.setattr(auth, "LOOPBACK", auth.LOOPBACK | {"testclient"})


def setup(client: TestClient, body: dict[str, Any] = FIRST, **headers: str) -> Any:
    return client.post("/api/v1/auth/setup", json=body, headers=headers)


def test_first_run_creates_one_account_signs_it_in_and_then_closes(client: TestClient, local: None) -> None:
    assert client.get("/api/v1/auth/setup").json() == {"needs_setup": True, "refusal": None}
    r = setup(client)
    assert r.status_code == 201, r.text
    assert r.json()["user"]["username"] == "ana.k" and r.json()["user"]["timezone"] == "America/New_York"
    assert r.json()["user"]["assistant"] is None
    session = client.get("/api/v1/auth/session")
    assert session.status_code == 200 and session.json()["user"]["username"] == "ana.k"

    assert client.get("/api/v1/auth/setup").json() == {"needs_setup": False, "refusal": None}
    again = setup(client, {**FIRST, "username": "intruder"})
    assert again.status_code == 409 and again.json()["code"] == "already_set_up"
    with new_session() as db:
        assert [u.username for u in db.scalars(select(User))] == ["ana.k"]
        created = db.scalars(select(AuditEvent).where(AuditEvent.action == "user.created")).one()
    assert created.details == {"via": "first_run", "timezone": "America/New_York"}
    assert "long local password" not in str(created.details)


@pytest.mark.parametrize(
    ("headers", "code"),
    [
        ({"Origin": "https://evil.example"}, "first_run_not_local"),
        ({"Sec-Fetch-Site": "cross-site"}, "first_run_not_local"),
    ],
)
def test_another_site_cannot_create_the_account(
    client: TestClient, local: None, headers: dict[str, str], code: str
) -> None:
    r = setup(client, **headers)
    assert r.status_code == 403 and r.json()["code"] == code
    assert setup(client, Origin="http://127.0.0.1:4318").status_code == 201


def test_only_on_this_computer_and_never_in_production(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.get("/api/v1/auth/setup").json() == {"needs_setup": True, "refusal": "not_local"}
    r = setup(client)
    assert r.status_code == 403 and r.json()["code"] == "first_run_not_local"

    monkeypatch.setattr(auth, "LOOPBACK", auth.LOOPBACK | {"testclient"})
    monkeypatch.setattr(get_settings(), "environment", "production")
    assert client.get("/api/v1/auth/setup").json()["refusal"] == "disabled"
    r = setup(client)
    assert r.status_code == 403 and r.json()["code"] == "first_run_disabled"
    with new_session() as db:
        assert db.scalar(select(User)) is None


def test_first_run_checks_the_input(client: TestClient, local: None) -> None:
    assert setup(client, {**FIRST, "timezone": "Mars/Olympus"}).json()["code"] == "invalid_timezone"
    assert setup(client, {**FIRST, "password": "short"}).status_code == 422
    assert setup(client, {**FIRST, "username": "a b"}).status_code == 422
    with new_session() as db:
        assert db.scalar(select(User)) is None


def test_the_learner_sets_time_zone_and_assistant(owner_api: Api) -> None:
    r = owner_api.client.put(
        "/api/v1/settings/profile", json={"assistant": "codex", "timezone": "Asia/Tokyo"}, headers=owner_api.headers()
    )
    assert r.status_code == 200, r.text
    assert r.json()["assistant"] == "codex" and r.json()["timezone"] == "Asia/Tokyo"
    assert owner_api.get("/auth/session").json()["user"]["assistant"] == "codex"

    later = owner_api.client.put("/api/v1/settings/profile", json={"assistant": None}, headers=owner_api.headers())
    assert later.json()["assistant"] is None and later.json()["timezone"] == "Asia/Tokyo"
    bad = owner_api.client.put("/api/v1/settings/profile", json={"timezone": "Nowhere"}, headers=owner_api.headers())
    assert bad.status_code == 422 and bad.json()["code"] == "invalid_timezone"
    wrong = owner_api.client.put("/api/v1/settings/profile", json={"assistant": "gemini"}, headers=owner_api.headers())
    assert wrong.status_code == 422
    with new_session() as db:
        changes = [e.details for e in db.scalars(select(AuditEvent).where(AuditEvent.action == "profile.changed"))]
    assert changes[0]["assistant"] == {"from": None, "to": "codex"}
    assert changes[1] == {"assistant": {"from": "codex", "to": None}}
