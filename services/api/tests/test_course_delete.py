"""Deleting a whole course: only with its exact name, soft, audited, everything in it hidden, restorable 30 days."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.main import create_app
from recallspring_api.models import AuditEvent

from .conftest import Api, ConnectorApi, FrozenClock, make_user


def delete(api: Api, course_id: str, title: str, key: str | None = None):  # type: ignore[no-untyped-def]
    return api.client.request(
        "DELETE", f"/api/v1/courses/{course_id}", json={"confirm_title": title}, headers=api.headers(key)
    )


def filled_course(api: Api) -> dict[str, str]:
    ids = api.course_with_question()
    course_id = ids["course_id"]
    api.post(
        "/notes",
        {"course_id": course_id, "client_note_id": str(uuid.uuid4()), "title": "Mine", "body": "x"},
    )
    target = api.post(
        "/targets",
        {
            "course_id": course_id,
            "name": "Midterm 1",
            "kind": "kolokvij",
            "due_date": "2026-12-20",
            "scope_description": "All",
        },
    )
    assert target.status_code in (200, 201), target.text
    return ids


def test_delete_needs_the_exact_name_and_hides_everything(owner_api: Api, conn: ConnectorApi) -> None:
    ids = filled_course(owner_api)
    course_id = ids["course_id"]
    title = owner_api.get(f"/courses/{course_id}").json()["title"]
    other = owner_api.post("/courses", {"title": "Chemistry"}).json()

    counts = owner_api.get(f"/courses/{course_id}/contents").json()["counts"]
    assert counts["materials"] == 1 and counts["notes"] == 1 and counts["exams"] == 1 and counts["concepts"] >= 1

    assert delete(owner_api, course_id, title.lower()).json()["code"] == "confirm_title_mismatch"
    assert delete(owner_api, course_id, title + " ").status_code == 422
    assert owner_api.get(f"/courses/{course_id}").status_code == 200  # nothing happened

    key = str(uuid.uuid4())
    gone = delete(owner_api, course_id, title, key)
    assert gone.status_code == 200 and gone.json()["restorable_days"] == 30
    assert delete(owner_api, course_id, title, key).headers.get("Idempotent-Replay") == "true"

    assert [c["id"] for c in owner_api.get("/courses").json()] == [other["id"]]
    assert owner_api.get(f"/courses/{course_id}").status_code == 404
    assert owner_api.get("/notes").json() == [] and owner_api.get("/sources").json() == []
    assert owner_api.get(f"/sources/{ids['source_id']}").status_code == 404
    assert owner_api.get(f"/questions/{ids['question_id']}").status_code == 404
    assert owner_api.get("/attempts").json() == [] and owner_api.get("/quizzes").json() == []
    assert owner_api.get("/reviews/due", horizon_days=60).json()["items"] == []
    assert [c["id"] for c in conn.get("/courses").json()] == [other["id"]]
    assert conn.get(f"/courses/{course_id}/context").status_code == 404

    with new_session() as db:
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "course.deleted"))
        assert audit is not None and audit.details["title"] == title and audit.details["notes"] == 1


def test_restore_brings_back_what_the_course_had_but_not_earlier_deletions(owner_api: Api) -> None:
    ids = filled_course(owner_api)
    course_id = ids["course_id"]
    title = owner_api.get(f"/courses/{course_id}").json()["title"]
    note = owner_api.post(
        "/notes", {"course_id": course_id, "client_note_id": str(uuid.uuid4()), "title": "Old", "body": "y"}
    ).json()
    owner_api.client.delete(f"/api/v1/notes/{note['id']}", headers=owner_api.headers())  # deleted on its own

    delete(owner_api, course_id, title)
    assert [c["id"] for c in owner_api.get("/courses/deleted").json()] == [course_id]
    restored = owner_api.post(f"/courses/{course_id}/restore")
    assert restored.status_code == 200
    assert owner_api.get("/courses/deleted").json() == []
    assert [n["title"] for n in owner_api.get("/notes").json()] == ["Mine"]  # "Old" stays deleted
    assert [n["id"] for n in owner_api.get("/notes/deleted").json()] == [note["id"]]
    assert len(owner_api.get("/sources").json()) == 1
    assert owner_api.get(f"/questions/{ids['question_id']}").status_code == 200


def test_restore_refuses_when_the_name_is_taken_and_after_30_days(owner_api: Api, frozen: FrozenClock) -> None:
    course = owner_api.post("/courses", {"title": "Physics"}).json()
    delete(owner_api, course["id"], "Physics")
    newer = owner_api.post("/courses", {"title": "Physics"}).json()
    taken = owner_api.post(f"/courses/{course['id']}/restore")
    assert taken.status_code == 409 and taken.json()["code"] == "course_exists"
    owner_api.patch(f"/courses/{newer['id']}", {"title": "Physics (new)"})
    assert owner_api.post(f"/courses/{course['id']}/restore").status_code == 200

    delete(owner_api, course["id"], "Physics")
    frozen.advance(days=31)
    assert owner_api.get("/courses/deleted").json() == []
    assert owner_api.post(f"/courses/{course['id']}/restore").status_code == 404


def test_another_learner_cannot_delete_or_restore(owner_api: Api) -> None:
    course = owner_api.post("/courses", {"title": "Mine"}).json()
    make_user("other")
    with TestClient(create_app()) as c:
        other = Api(c)
        other.login("other")
        assert delete(other, course["id"], "Mine").status_code == 404
        assert other.post(f"/courses/{course['id']}/restore").status_code == 404
        assert other.get(f"/courses/{course['id']}/contents").status_code == 404
    assert owner_api.get(f"/courses/{course['id']}").status_code == 200
