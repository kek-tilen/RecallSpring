"""Organising courses (university → faculty → semester), colours, archive, editing exams, answering simulations in
the web app, calendar export and images as material."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.models import Attempt, AuditEvent

from .conftest import Api, ConnectorApi, FrozenClock
from .test_planning_and_simulations import course_with_concepts, make_quiz, target

PNG = bytes.fromhex("89504e470d0a1a0a") + b"\0" * 32
JPEG = bytes.fromhex("ffd8ffe0") + b"\0" * 32


def test_groups_nest_and_refuse_cycles(owner_api: Api) -> None:
    uni = owner_api.post("/groups", {"kind": "university", "name": "Univerza v Mariboru"}).json()
    fac = owner_api.post("/groups", {"kind": "faculty", "name": "FERI", "parent_id": uni["id"]}).json()
    sem = owner_api.post(
        "/groups",
        {"kind": "semester", "name": "5. semester", "parent_id": fac["id"], "starts_on": "2026-10-01"},
    ).json()
    assert sem["parent_id"] == fac["id"] and sem["status"] == "active"

    cycle = owner_api.patch(f"/groups/{uni['id']}", {"parent_id": sem["id"]})
    assert cycle.status_code == 422 and cycle.json()["code"] == "invalid_parent"
    bad_dates = owner_api.patch(f"/groups/{sem['id']}", {"ends_on": "2026-09-01"})
    assert bad_dates.status_code == 422
    renamed = owner_api.patch(f"/groups/{sem['id']}", {"name": "5. semester (zima)"}).json()
    assert renamed["name"] == "5. semester (zima)"
    top = owner_api.patch(f"/groups/{fac['id']}", {"parent_id": None}).json()
    assert top["parent_id"] is None
    assert {g["name"] for g in owner_api.get("/groups").json()} == {"Univerza v Mariboru", "FERI", "5. semester (zima)"}


def test_course_colour_semester_and_archive(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Nmap"], known=True)
    fac = owner_api.post("/groups", {"kind": "faculty", "name": "FERI"}).json()
    sem = owner_api.post("/groups", {"kind": "semester", "name": "5. semester", "parent_id": fac["id"]}).json()

    patched = owner_api.patch(f"/courses/{course}", {"color": "violet", "group_id": sem["id"]}).json()
    assert patched["color"] == "violet" and patched["group_id"] == sem["id"]
    assert owner_api.patch(f"/courses/{course}", {"color": "#ff0000"}).status_code == 422
    assert owner_api.patch(f"/courses/{course}", {"group_id": str(uuid.uuid4())}).status_code == 404
    summary = owner_api.get("/overview/courses").json()[0]
    assert summary["group_path"] == ["FERI", "5. semester"] and summary["color"] == "violet"

    # A due review in the semester's course, then archive the faculty: everything inside is archived.
    quiz = make_quiz(conn, course, ids["Nmap"])
    form = conn.post(f"/quizzes/{quiz['quiz_id']}/open").json()
    conn.post(
        f"/quizzes/{quiz['quiz_id']}/submit",
        {
            "client_request_id": str(uuid.uuid4()),
            "answers": [{"question_id": form["items"][0]["question_id"], "option": "A"}],
        },
    )
    frozen.advance(days=3)
    archived = owner_api.post(f"/groups/{fac['id']}/archive", {"archived": True}).json()
    assert archived["courses_changed"] == 1 and all(g["status"] == "archived" for g in archived["groups"])
    assert owner_api.get("/overview/courses").json()[0]["status"] == "archived"
    plan = owner_api.get("/planner/today").json()
    assert plan["items"] and {i["category"] for i in plan["items"]} == {"Maintain"}
    assert "Archived course" in plan["items"][0]["why_selected"]

    owner_api.patch(f"/courses/{course}", {"long_term_retention": False})
    assert owner_api.get("/planner/today").json()["items"] == []

    restored = owner_api.post(f"/groups/{fac['id']}/archive", {"archived": False}).json()
    assert restored["courses_changed"] == 1
    assert owner_api.get("/overview/courses").json()[0]["status"] == "active"
    with new_session() as db:
        actions = {a.action for a in db.scalars(select(AuditEvent))}
    assert {"group.archived", "group.restored", "course.updated"} <= actions


def test_exam_dates_move_and_results_are_recorded_from_the_web_app(
    owner_api: Api, conn: ConnectorApi, frozen: FrozenClock
) -> None:
    course, _ = course_with_concepts(owner_api, conn, ["Nmap"])
    t = target(conn, course, "1. kolokvij", "2026-12-01", [])
    moved = owner_api.patch(f"/targets/{t['id']}", {"due_date": "2026-12-05"}).json()
    assert moved["due_date"] == "2026-12-05" and moved["days_left"] == 16
    passed = owner_api.patch(f"/targets/{t['id']}", {"status": "passed", "result": "78 %"}).json()
    assert passed["status"] == "passed" and passed["result"] == "78 %"
    created = owner_api.post(
        "/targets",
        {"course_id": course, "kind": "izpit", "name": "Izpit", "due_date": "2027-01-20", "scope_description": "vse"},
    )
    assert created.status_code == 201
    timeline = owner_api.get("/targets").json()
    assert [x["name"] for x in timeline] == ["1. kolokvij", "Izpit"] and timeline[0]["course_id"] == course
    with new_session() as db:
        audits = [a for a in db.scalars(select(AuditEvent).where(AuditEvent.action == "target.updated"))]
    assert all(a.details["origin"] == "web" for a in audits) and len(audits) == 2


def test_simulation_answered_in_the_web_app_waits_for_claude(owner_api: Api, conn: ConnectorApi) -> None:
    course, ids = course_with_concepts(owner_api, conn, ["Nmap"], known=True)
    quiz = make_quiz(conn, course, ids["Nmap"])
    qid = quiz["quiz_id"]
    form = owner_api.post(f"/quizzes/{qid}/open").json()
    assert all("correct_option" not in i and "expected_points" not in i for i in form["items"])
    q = [i["question_id"] for i in form["items"]]
    assert (
        owner_api.post(f"/quizzes/{qid}/draft", {"answers": [{"question_id": q[0], "option": "A"}]}).status_code == 200
    )
    exact = "Ker ne dobi odgovora.\n  (iz spletne aplikacije)"
    result = owner_api.post(
        f"/quizzes/{qid}/submit",
        {"client_request_id": str(uuid.uuid4()), "answers": [{"question_id": q[2], "text": exact}]},
    ).json()
    assert result["status"] == "submitted" and result["pending_items"] == 1
    with new_session() as db:
        vias = {a.captured_via for a in db.scalars(select(Attempt).where(Attempt.quiz_id == uuid.UUID(qid)))}
    assert vias == {"app_ui"}
    to_grade = conn.get("/quizzes", needs_grading="true").json()
    assert [x["id"] for x in to_grade] == [qid]
    open_item = next(i for i in conn.get(f"/quizzes/{qid}/results").json()["items"] if i["type"] == "open")
    assert open_item["answer"] == exact


def test_calendar_export_is_valid_icalendar(owner_api: Api, conn: ConnectorApi) -> None:
    course, _ = course_with_concepts(owner_api, conn, ["Nmap"])
    long_scope = "Od 1. do 6. predavanja; vključno z vajami, brez 7. poglavja. " * 3
    target(conn, course, "1. kolokvij", "2026-12-01", [], notes="Brez zapiskov")
    t2 = target(conn, course, "Izpit", "2027-01-20", [])
    conn.post(f"/targets/{t2['id']}/update", {"scope_description": long_scope})
    passed = target(conn, course, "Stari", "2026-11-01", [])
    conn.post(f"/targets/{passed['id']}/update", {"status": "passed"})

    r = owner_api.get("/calendar.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
    assert "attachment" in r.headers["content-disposition"]
    body = r.content.decode("utf-8")
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert body.count("BEGIN:VEVENT") == 2 and "Stari" not in body
    assert "DTSTART;VALUE=DATE:20261201" in body and "DTEND;VALUE=DATE:20261202" in body
    assert "TRIGGER:-P1D" in body
    assert all(len(line.encode("utf-8")) <= 75 for line in body.split("\r\n"))
    unfolded = body.replace("\r\n ", "")
    assert "predavanja\\; vključno z vajami\\, brez" in unfolded
    assert "\\nNotes: Brez zapiskov" in unfolded


def test_images_are_kept_as_material_without_extraction(owner_api: Api, conn: ConnectorApi) -> None:
    course, _ = course_with_concepts(owner_api, conn, ["Nmap"])
    photo = owner_api.upload(course, "zvezek-vaje-3.png", PNG, category="exercises")
    assert photo.status_code == 201, photo.text
    body = photo.json()
    assert body["kind"] == "image" and body["parse_state"] == "ready" and body["category"] == "exercises"
    assert body["parse_message"] is None and body["section_count"] == 0

    assert owner_api.upload(course, "fake.jpg", PNG).json()["code"] == "content_does_not_match_type"
    assert owner_api.upload(course, "drawing.svg", b"<svg/>").json()["code"] == "unsupported_file_type"
    jpeg = owner_api.upload(course, "predavanje.jpg", JPEG)
    assert jpeg.json()["category"] == "material"
    recategorised = owner_api.patch(f"/sources/{jpeg.json()['id']}", {"category": "notes"}).json()
    assert recategorised["category"] == "notes"

    seen = conn.client.get(f"/api/v1/connector/sources/{body['id']}/image", headers=conn.auth)
    assert seen.status_code == 200 and seen.content == PNG and seen.headers["content-type"] == "image/png"
    outline = conn.get(f"/courses/{course}/outline").json()
    assert {s["category"] for s in outline["sources"]} == {"exercises", "notes"}
