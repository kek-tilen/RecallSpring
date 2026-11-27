"""Recently deleted in one list (Settings › Data & backups, 2026-11-27): courses, exams, notes, focus blocks and chats
of the last 30 days, newest first; what a deleted course holds comes back with it and is not listed apart."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.main import create_app
from recallspring_api.models import AiConversation, User

from .conftest import Api, FrozenClock, make_user
from .test_course_delete import delete, filled_course
from .test_focus import block


def _note(api: Api, course_id: str, title: str) -> str:
    r = api.post("/notes", {"course_id": course_id, "client_note_id": str(uuid.uuid4()), "title": title, "body": "x"})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def _delete(api: Api, path: str) -> int:
    return api.client.delete(f"/api/v1{path}", headers=api.headers()).status_code


def test_one_list_newest_first_with_what_a_course_brings_back(owner_api: Api, frozen: FrozenClock) -> None:
    assert owner_api.get("/deleted").json() == {"restorable_days": 30, "items": []}
    stats = owner_api.post("/courses", {"title": "Statistics"}).json()["id"]

    ids = filled_course(owner_api)  # a course with a note and an exam
    title = owner_api.get(f"/courses/{ids['course_id']}").json()["title"]
    assert delete(owner_api, ids["course_id"], title).status_code == 200

    frozen.advance(hours=1)
    focus = owner_api.post("/focus-sessions", block(course_id=stats)).json()["id"]
    assert _delete(owner_api, f"/focus-sessions/{focus}") == 200
    with new_session() as db:
        owner = db.scalar(select(User).where(User.username == "owner"))
        assert owner is not None
        chat = AiConversation(user_id=owner.id, provider="chatgpt", title="Variance", course_id=stats)
        chat.deleted_at = frozen()
        db.add(chat)
        db.commit()
        chat_id = str(chat.id)

    frozen.advance(hours=1)
    note = _note(owner_api, stats, "Hypothesis tests")
    assert _delete(owner_api, f"/notes/{note}") == 200

    view = owner_api.get("/deleted").json()
    kinds = [(i["type"], i["title"], i["course_title"]) for i in view["items"]]
    assert kinds[0] == ("note", "Hypothesis tests", "Statistics")
    assert set(kinds[1:3]) == {("focus", "Focus block", "Statistics"), ("chat", "Variance", "Statistics")}
    assert kinds[3] == ("course", title, None) and len(kinds) == 4  # its note and exam are not listed apart
    course = view["items"][3]
    assert course["brings"] == {"notes": 1, "exams": 1, "materials": 1}
    assert course["restorable_until"].startswith("2026-12-19")
    assert {i["id"] for i in view["items"]} >= {focus, chat_id, note}

    # Restoring uses each item's own endpoint; the list follows.
    assert owner_api.post(f"/notes/{note}/restore", {}).status_code == 200
    assert "note" not in {i["type"] for i in owner_api.get("/deleted").json()["items"]}

    # After 30 days an item leaves the list.
    frozen.advance(days=30, minutes=1)
    assert owner_api.get("/deleted").json()["items"] == []


def test_a_course_restored_shows_what_was_deleted_before_it(owner_api: Api, frozen: FrozenClock) -> None:
    ids = filled_course(owner_api)
    course_id = ids["course_id"]
    title = owner_api.get(f"/courses/{course_id}").json()["title"]
    earlier = _note(owner_api, course_id, "Deleted first")
    assert _delete(owner_api, f"/notes/{earlier}") == 200
    frozen.advance(minutes=5)
    assert delete(owner_api, course_id, title).status_code == 200
    items = owner_api.get("/deleted").json()["items"]
    assert [i["type"] for i in items] == ["course"] and items[0]["brings"]["notes"] == 1

    assert owner_api.post(f"/courses/{course_id}/restore", {}).status_code == 200
    items = owner_api.get("/deleted").json()["items"]
    assert [(i["type"], i["title"]) for i in items] == [("note", "Deleted first")]
    frozen.advance(days=29)
    assert owner_api.get("/deleted").json()["items"][0]["id"] == earlier
    frozen.advance(days=1, minutes=1)
    assert owner_api.get("/deleted").json()["items"] == []


def test_only_the_learners_own_items(owner_api: Api) -> None:
    course = owner_api.post("/courses", {"title": "Mine"}).json()["id"]
    note = _note(owner_api, course, "Private")
    assert _delete(owner_api, f"/notes/{note}") == 200
    make_user("second")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        assert other.login("second").status_code == 200
        assert other.get("/deleted").json()["items"] == []
