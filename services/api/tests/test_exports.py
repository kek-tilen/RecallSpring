"""Export (BYOS step 1): the learner's own material, notes and answers as plain files (services/exports.py)."""

from __future__ import annotations

import csv
import io
import json
import uuid
import zipfile
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.main import create_app
from recallspring_api.models import AuditEvent, Export
from recallspring_api.services import exports
from recallspring_api.services.exports import Names, safe_name

from .conftest import Api, FrozenClock, make_user, run_pending


def _zip(api: Api, export_id: str) -> zipfile.ZipFile:
    r = api.client.get(f"/api/v1/exports/{export_id}/download")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert "RecallSpring export" in r.headers["content-disposition"]
    return zipfile.ZipFile(io.BytesIO(r.content))


def _make(api: Api, **body: Any) -> dict[str, Any]:
    r = api.post("/exports", body)
    assert r.status_code == 202, r.text
    return r.json()["current"]


def _note(api: Api, course_id: str, title: str, body: str) -> None:
    r = api.post("/notes", {"course_id": course_id, "client_note_id": str(uuid.uuid4()), "title": title, "body": body})
    assert r.status_code == 201, r.text


def _actions() -> list[str]:
    with new_session() as db:
        return list(db.scalars(select(AuditEvent.action).order_by(AuditEvent.occurred_at)))


def test_names_work_on_every_system() -> None:
    assert safe_name('Lab: week 3 / "draft"?') == "Lab- week 3 - -draft--"
    assert safe_name("CON.txt") == "_CON.txt"
    assert safe_name("  ..  ") == "untitled"
    assert safe_name("Čebelarstvo – zapiski.md") == "Čebelarstvo – zapiski.md"
    long = safe_name("x" * 300 + ".pdf")
    assert len(long) == 120 and long.endswith(".pdf")
    names = Names()
    assert names.take("a", "Notes.md") == "a/Notes.md"
    assert names.take("a", "notes.md") == "a/notes (2).md"
    assert names.take("a", "README") == "a/README"
    assert names.take("a", "readme") == "a/readme (2)"


def test_export_holds_material_notes_and_answers(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    up = owner_api.upload(ids["course_id"], "Lab sheet.txt", b"Measure the CO2 output.")
    assert up.status_code in (200, 201), up.text
    _note(owner_api, ids["course_id"], "Glycolysis / part 1", "My own words, kept exactly.\n")
    attempt_id = owner_api.answer(ids["question_id"]).json()["attempt_id"]
    ai = owner_api.post(f"/attempts/{attempt_id}/evaluate").json()["assessments"][0]
    owner_api.post(f"/assessments/{ai['id']}/challenge", {"reason": "Both points covered", "corrected_grade": 3})
    owner_api.answer(ids["question_id"], kind="dont_know", text="")

    view = owner_api.get("/exports").json()
    course = view["courses"][0]
    assert (course["files"], course["notes"], course["answers"]) == (2, 1, 2) and course["bytes"] > 0
    assert view["current"] is None and view["keep_hours"] == 24

    current = _make(owner_api)
    assert current["state"] == "queued"
    run_pending()
    current = owner_api.get("/exports").json()["current"]
    assert current["state"] == "ready" and current["counts"] == {"files": 2, "notes": 1, "answers": 2}
    waiting = owner_api.get("/dashboard").json()["attention"]
    assert any(a["kind"] == "export" and a["title"] == "Your export is ready" for a in waiting)

    zf = _zip(owner_api, current["id"])
    names = zf.namelist()
    root = names[0].split("/")[0]
    assert root.startswith("RecallSpring export ")
    assert f"{root}/README.txt" in names and f"{root}/answers.json" in names
    assert any(n.startswith(f"{root}/Biology 101/material/") and n.endswith("Lab sheet.txt") for n in names)
    note = next(n for n in names if "/notes/" in n)
    assert note.endswith("Glycolysis - part 1.md")
    assert zf.read(note).decode() == "My own words, kept exactly.\n"
    assert zf.read(next(n for n in names if n.endswith("Lab sheet.txt"))) == b"Measure the CO2 output."
    assert "not a\nvalidated test score" in zf.read(f"{root}/README.txt").decode()

    rows = list(csv.DictReader(io.StringIO(zf.read(f"{root}/Biology 101/answers.csv").decode("utf-8-sig"))))
    assert rows[0]["grade"] == "3" and rows[0]["grade_label"] == "Solid" and rows[0]["overridden"] == "yes"
    assert rows[0]["graded_by"] == "You" and rows[0]["concept"] == "Glycolysis"
    assert rows[0]["bloom_level"] == "4 Analyze"
    assert rows[1]["answer_kind"] == "dont_know"
    full = json.loads(zf.read(f"{root}/answers.json"))
    first = full["answers"][0]
    assert len(first["assessments"]) == 2 and first["grade_in_force"]["overridden"] is True
    assert first["question"]["prompt"].startswith("Compare glycolysis")

    assert "export.created" in _actions() and "export.downloaded" in _actions()
    assert owner_api.get("/exports").json()["current"]["downloaded_at"]
    assert not any(a["kind"] == "export" for a in owner_api.get("/dashboard").json()["attention"])


def test_choose_courses_and_parts(owner_api: Api) -> None:
    a = owner_api.post("/courses", {"title": "Physics"}).json()["id"]
    b = owner_api.post("/courses", {"title": "History"}).json()["id"]
    _note(owner_api, a, "Forces", "F = ma")
    _note(owner_api, b, "Rome", "753 BC")
    owner_api.paste(a, "# Mechanics\nNewton.")
    current = _make(owner_api, course_ids=[a], material=False, answers=False)
    assert current["options"] == {"course_ids": [a], "material": False, "notes": True, "answers": False}
    run_pending()
    current = owner_api.get("/exports").json()["current"]
    names = _zip(owner_api, current["id"]).namelist()
    assert any("/Physics/notes/" in n for n in names)
    assert not any("History" in n or "/material/" in n or n.endswith(".csv") or n.endswith(".json") for n in names)


def test_one_at_a_time_and_refusals(owner_api: Api, client: TestClient) -> None:
    cid = owner_api.post("/courses", {"title": "Physics"}).json()["id"]
    nothing = owner_api.post("/exports", {"material": False, "notes": False, "answers": False})
    assert nothing.status_code == 422 and nothing.json()["code"] == "nothing_to_export"
    unknown = owner_api.post("/exports", {"course_ids": [str(uuid.uuid4())]})
    assert unknown.status_code == 404
    first = _make(owner_api, course_ids=[cid])
    busy = owner_api.post("/exports", {})
    assert busy.status_code == 409 and busy.json()["code"] == "export_running"
    run_pending()

    make_user("second")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        assert other.login("second").status_code == 200
        assert other_client.get(f"/api/v1/exports/{first['id']}/download").status_code == 404
        assert other.post("/exports", {"course_ids": [cid]}).status_code == 404  # not their course
        assert other.get("/exports").json()["courses"] == []


def test_stop_and_remove(owner_api: Api) -> None:
    cid = owner_api.post("/courses", {"title": "Physics"}).json()["id"]
    _note(owner_api, cid, "Forces", "F = ma")
    current = _make(owner_api)
    stopped = owner_api.post(f"/exports/{current['id']}/cancel")
    assert stopped.status_code == 200 and stopped.json()["current"]["state"] == "cancelled"
    run_pending()
    assert owner_api.get("/exports").json()["current"]["state"] == "cancelled"

    current = _make(owner_api)
    run_pending()
    with new_session() as db:
        row = db.get(Export, uuid.UUID(current["id"]))
        assert row is not None and exports.zip_path(row).exists()
        path = exports.zip_path(row)
    removed = owner_api.post(f"/exports/{current['id']}/cancel")
    assert removed.json()["current"]["state"] == "expired" and not path.exists()
    gone = owner_api.client.get(f"/api/v1/exports/{current['id']}/download")
    assert gone.status_code == 410 and gone.json()["code"] == "export_gone"


def test_finished_exports_are_deleted_after_a_day(owner_api: Api, frozen: FrozenClock) -> None:
    cid = owner_api.post("/courses", {"title": "Physics"}).json()["id"]
    _note(owner_api, cid, "Forces", "F = ma")
    current = _make(owner_api)
    run_pending()
    with new_session() as db:
        row = db.get(Export, uuid.UUID(current["id"]))
        assert row is not None
        path = exports.zip_path(row)
    frozen.advance(hours=23)
    assert exports.expire_all() == 0 and path.exists()
    frozen.advance(hours=2)
    assert exports.expire_all() == 1 and not path.exists()
    assert owner_api.get("/exports").json()["current"]["state"] == "expired"
    assert owner_api.get("/exports").json()["last_export_at"]
