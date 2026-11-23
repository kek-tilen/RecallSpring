"""ADR-011: a note or summary the learner gave in an assistant chat is saved (after they confirmed it) exactly as the
assistant sent it, marked as transcribed; with concepts it is a learning summary and they become studied."""

from __future__ import annotations

import uuid
from typing import Any

from .conftest import Api, ConnectorApi


def note(conn: ConnectorApi, course_id: str, **extra: Any) -> Any:
    body = {"course_id": course_id, "title": "Kibernetski napadi", "text": "• Ranljivost\n  ◦ šibkost [?]", **extra}
    body.setdefault("client_request_id", str(uuid.uuid4()))
    return conn.post("/notes", body, key=body["client_request_id"])


def test_a_chat_note_is_saved_exactly_and_marked_transcribed(owner_api: Api, conn: ConnectorApi) -> None:
    ids = owner_api.course_with_question()
    key = str(uuid.uuid4())
    r = note(conn, ids["course_id"], transcribed_from_photo=True, client_request_id=key)
    assert r.status_code == 201, r.text
    saved = r.json()
    assert saved["captured_via"] == "assistant_transcription" and saved["concepts"] == []
    again = note(conn, ids["course_id"], transcribed_from_photo=True, client_request_id=key)  # a retry saves nothing
    assert again.json()["note_id"] == saved["note_id"]

    mine = owner_api.get(f"/notes/{saved['note_id']}").json()
    assert mine["body"] == "• Ranljivost\n  ◦ šibkost [?]" and mine["captured_via"] == "assistant_transcription"
    listed = conn.get("/notes", course_id=ids["course_id"]).json()
    assert [n["captured_via"] for n in listed] == ["assistant_transcription"]
    # concepts stay as they were: an ordinary note is not a learning summary
    assert owner_api.get(f"/concepts/{ids['concept_id']}/detail").json()["study_status"] == "not_studied"


def test_a_chat_summary_marks_its_concepts_studied(owner_api: Api, conn: ConnectorApi) -> None:
    ids = owner_api.course_with_question()
    r = note(conn, ids["course_id"], text="Glycolysis splits glucose.", concept_ids=[ids["concept_id"]])
    assert r.status_code == 201, r.text
    assert [c["study_status"] for c in r.json()["concepts"]] == ["studied"]
    assert owner_api.get(f"/concepts/{ids['concept_id']}/detail").json()["study_status"] == "studied"


def test_chat_notes_are_checked(owner_api: Api, conn: ConnectorApi) -> None:
    ids = owner_api.course_with_question()
    assert note(conn, ids["course_id"], text="   ").json()["code"] == "empty_note"
    other = owner_api.post("/courses", {"title": "Chemistry"}).json()
    wrong = note(conn, other["id"], concept_ids=[ids["concept_id"]])  # a concept of another course
    assert wrong.status_code == 404
    assert note(conn, str(uuid.uuid4())).status_code == 404


def test_notes_written_in_the_app_stay_app_notes(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    body = {"course_id": ids["course_id"], "client_note_id": str(uuid.uuid4()), "title": "Mine", "body": "typed"}
    r = owner_api.post("/notes", body)
    assert r.status_code in (200, 201), r.text
    assert r.json()["captured_via"] == "app_ui"


def test_migration_marks_existing_summaries(owner_api: Api, conn: ConnectorApi) -> None:
    """0025 back-fills notes the summary form saved as summary_form and leaves the others app_ui."""
    import os

    from alembic import command
    from sqlalchemy import select

    from recallspring_api.db import get_engine, new_session
    from recallspring_api.models import Note

    from .conftest import alembic_config

    ids = owner_api.course_with_question()
    summary = {
        "course_id": ids["course_id"],
        "concept_ids": [ids["concept_id"]],
        "title": "Chunk 1",
        "text": "My summary.",
        "client_request_id": str(uuid.uuid4()),
    }
    assert conn.post("/learning", summary, key=summary["client_request_id"]).status_code == 201
    typed = {"course_id": ids["course_id"], "client_note_id": str(uuid.uuid4()), "title": "Typed", "body": "x"}
    assert owner_api.post("/notes", typed).status_code in (200, 201)

    get_engine().dispose()
    cfg = alembic_config(os.environ["RS_DATABASE_URL"])
    command.downgrade(cfg, "0024")
    command.upgrade(cfg, "head")
    with new_session() as db:
        assert {n.title: n.captured_via for n in db.scalars(select(Note))} == {
            "Chunk 1": "summary_form",
            "Typed": "app_ui",
        }
