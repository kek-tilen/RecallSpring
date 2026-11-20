"""Several Claude chats share one learner's records: duplicates are refused, existing ones can be merged, and an
exam can be deleted (soft, restorable) from the web app only."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent, StudyTarget, User

from .conftest import Api, ConnectorApi, FrozenClock, make_user
from .test_planning_and_simulations import course_with_concepts, make_quiz, target


def test_a_second_chat_cannot_add_the_same_kolokvij_or_course(owner_api: Api, conn: ConnectorApi) -> None:
    course, _ = course_with_concepts(owner_api, conn, ["Nmap"])
    first = target(conn, course, "1. kolokvij", "2026-11-30", [])
    same_day = conn.post(
        "/targets",
        {
            "course_id": course,
            "kind": "kolokvij",
            "name": "Kolokvij",
            "due_date": "2026-11-30",
            "scope_description": "x",
        },
    )
    assert same_day.status_code == 409 and same_day.json()["code"] == "target_exists"
    assert same_day.json()["details"]["existing"]["id"] == first["id"] and first["id"] in same_day.json()["message"]
    same_name = conn.post(
        "/targets",
        {
            "course_id": course,
            "kind": "kolokvij",
            "name": "1. Kolokvij ",
            "due_date": "2026-12-02",
            "scope_description": "x",
        },
    )
    assert same_name.status_code == 409
    second = conn.post(
        "/targets",
        {
            "course_id": course,
            "kind": "kolokvij",
            "name": "2. kolokvij",
            "due_date": "2027-01-15",
            "scope_description": "y",
        },
    )
    assert second.status_code == 201
    web = owner_api.post(
        "/targets",
        {
            "course_id": course,
            "kind": "kolokvij",
            "name": "1. kolokvij",
            "due_date": "2026-11-30",
            "scope_description": "z",
        },
    )
    assert web.status_code == 409

    again = conn.post("/courses", {"title": " komunikacijska  VARNOST "})
    assert again.status_code == 409 and again.json()["code"] == "course_exists"
    assert again.json()["details"]["existing"]["id"] == course
    assert owner_api.post("/courses", {"title": "Komunikacijska varnost"}).status_code == 409


def _insert_duplicate(course_id: str, name: str, due: str, notes: str | None = None) -> str:
    """A duplicate created before the duplicate check existed (as in the owner's database)."""
    with new_session() as db:
        user = db.scalar(select(User).where(User.username == "owner"))
        assert user is not None
        t = StudyTarget(
            user_id=user.id,
            course_id=uuid.UUID(course_id),
            kind="kolokvij",
            name=name,
            due_date=dt.date.fromisoformat(due),
            scope_description="Kolokvij 30. 11. (pisno, brez pripomočkov)",
            notes=notes,
            goal="long_term",
        )
        db.add(t)
        db.commit()
        return str(t.id)


def test_duplicates_are_flagged_and_merged_without_losing_anything(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Nmap"], known=True)
    kept = target(conn, course, "1. kolokvij", "2026-11-30", [])
    conn.post(f"/targets/{kept['id']}/profile", {"item_types": [{"type": "mcq", "share": 1.0}], "notes": "old paper"})
    make_quiz(conn, course, ids["Nmap"], target_id=kept["id"])
    dup = _insert_duplicate(course, "Kolokvij", "2026-11-30", notes="60 minut")

    timeline = {t["id"]: t for t in owner_api.get("/targets").json()}
    assert timeline[kept["id"]]["duplicates"] == [dup] and timeline[dup]["duplicates"] == [kept["id"]]
    assert timeline[kept["id"]]["simulations"] == 1

    merged = owner_api.post(f"/targets/{dup}/merge", {"into_id": kept["id"]})
    assert merged.status_code == 200, merged.text
    body = merged.json()
    assert body["id"] == kept["id"] and body["profile"]["notes"] == "old paper"
    assert "pisno, brez pripomočkov" in body["notes"] and "60 minut" in body["notes"]
    after = owner_api.get("/targets").json()
    assert [t["id"] for t in after] == [kept["id"]] and after[0]["duplicates"] == []
    assert [d["id"] for d in owner_api.get("/targets/deleted").json()] == [dup]
    with new_session() as db:
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "target.merged"))
    assert audit is not None and audit.details["simulations_moved"] == 0 and audit.details["merged"]["id"] == dup

    assert owner_api.post(f"/targets/{kept['id']}/merge", {"into_id": kept["id"]}).status_code == 422


def test_delete_is_soft_restorable_and_web_only(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    course, _ = course_with_concepts(owner_api, conn, ["Nmap"])
    t = target(conn, course, "1. kolokvij", "2026-11-30", [])
    deleted = owner_api.client.delete(f"/api/v1/targets/{t['id']}", headers=owner_api.headers())
    assert deleted.status_code == 200 and deleted.json()["restorable_days"] == 30
    assert owner_api.get("/targets").json() == []
    context = conn.get(f"/courses/{course}/context").json()
    assert context["active_target"] is None and context["other_targets"] == []
    # Claude cannot delete; the same exam can be recorded again once the old one is deleted.
    assert conn.client.delete(f"/api/v1/connector/targets/{t['id']}", headers=conn.auth).status_code in (404, 405)
    no_csrf = owner_api.client.delete(f"/api/v1/targets/{t['id']}", headers={"Idempotency-Key": str(uuid.uuid4())})
    assert no_csrf.status_code == 403

    restored = owner_api.post(f"/targets/{t['id']}/restore")
    assert restored.status_code == 200 and restored.json()["name"] == "1. kolokvij"
    assert [x["id"] for x in owner_api.get("/targets").json()] == [t["id"]]

    make_user("intruder")
    from fastapi.testclient import TestClient

    from recallspring_api.main import create_app

    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        assert other.login("intruder").status_code == 200
        r = other.client.delete(f"/api/v1/targets/{t['id']}", headers=other.headers())
        assert r.status_code == 404
    with new_session() as db:
        actions = [a.action for a in db.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at))]
    assert "target.deleted" in actions and "target.restored" in actions
