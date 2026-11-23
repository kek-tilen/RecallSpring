"""Settings -> Profile: what Home calls the learner (ADR-012, migration 0026)."""

from __future__ import annotations

from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent

from .conftest import Api


def put(api: Api, body: dict):
    return api.client.put("/api/v1/settings/profile", json=body, headers=api.headers())


def test_no_name_by_default_then_set_tidy_and_cleared(owner_api: Api) -> None:
    assert owner_api.get("/auth/session").json()["user"]["greeting_name"] is None

    r = put(owner_api, {"greeting_name": "  Tina   M. "})
    assert r.status_code == 200, r.text
    assert r.json()["greeting_name"] == "Tina M."  # spaces tidied
    assert owner_api.get("/auth/session").json()["user"]["greeting_name"] == "Tina M."

    keep = put(owner_api, {"timezone": "Europe/Ljubljana"})  # not sent = unchanged
    assert keep.json()["greeting_name"] == "Tina M."
    assert put(owner_api, {"greeting_name": "   "}).json()["greeting_name"] is None  # blank = no name
    assert put(owner_api, {"greeting_name": "x" * 41}).status_code == 422

    with new_session() as db:
        changes = [
            e.details
            for e in db.scalars(select(AuditEvent).where(AuditEvent.action == "profile.changed"))
            if "greeting_name" in e.details
        ]
    assert [c["greeting_name"] for c in changes] == [{"set": True}, {"set": False}]
    assert "Tina" not in str(changes)  # the name stays out of the audit log
