"""Usually studied in (2026-11-27; migration 0037): one optional assistant per course, wording only, audited."""

from __future__ import annotations

from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent

from .conftest import Api, ConnectorApi
from .test_learning_first import course


def test_a_course_names_the_assistant_it_is_usually_studied_in(owner_api: Api, conn: ConnectorApi) -> None:
    cid, _ = course(conn, ["Topic"])
    listed = {c["id"]: c for c in owner_api.get("/courses").json()}
    assert listed[cid]["usually_studied_in"] is None
    r = owner_api.put(f"/courses/{cid}/studied-in", {"assistant": "codex"})
    assert r.status_code == 200 and r.json()["usually_studied_in"] == "codex"
    assert owner_api.put(f"/courses/{cid}/studied-in", {"assistant": "codex"}).status_code == 200  # no change
    assert owner_api.put(f"/courses/{cid}/studied-in", {"assistant": None}).json()["usually_studied_in"] is None
    assert owner_api.put(f"/courses/{cid}/studied-in", {"assistant": "gemini"}).status_code == 422
    with new_session() as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "course.studied_in_changed").order_by(AuditEvent.occurred_at)
        ).all()
        assert [e.details for e in events] == [{"from": None, "to": "codex"}, {"from": "codex", "to": None}]
    # Wording only: the connector still works with the course whatever is chosen.
    owner_api.put(f"/courses/{cid}/studied-in", {"assistant": "chatgpt"})
    assert conn.get(f"/courses/{cid}/outline").status_code == 200
