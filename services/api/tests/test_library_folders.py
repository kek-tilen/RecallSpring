"""Library folders (optional, per course, nestable) and archiving material: reversible, nothing deleted."""

from __future__ import annotations

import uuid
from typing import Any

from recallspring_api.ingest.jobs import run_pending

from .conftest import Api, ConnectorApi

TEXT = "# Cells\n\n## Membrane\n\nThe membrane is a lipid bilayer with mitochondrial pumps.\n"


def _delete(api: Api, path: str) -> Any:
    return api.client.delete(f"/api/v1{path}", headers=api.headers())


def _setup(api: Api) -> tuple[str, str]:
    course = api.post("/courses", {"title": "Biology"}).json()["id"]
    other = api.post("/courses", {"title": "Physics"}).json()["id"]
    return course, other


def test_folders_nest_rename_move_and_refuse_bad_moves(owner_api: Api) -> None:
    course, other = _setup(owner_api)
    lectures = owner_api.post("/folders", {"course_id": course, "name": "  Lectures  "}).json()
    assert lectures["name"] == "Lectures" and lectures["path"] == "Lectures" and lectures["parent_id"] is None
    week = owner_api.post("/folders", {"course_id": course, "parent_id": lectures["id"], "name": "Week 3/4"}).json()
    assert week["path"] == "Lectures / Week 3-4"  # a slash separates levels, so it is replaced in names

    dup = owner_api.post("/folders", {"course_id": course, "name": "lectures"})
    assert dup.status_code == 409 and dup.json()["details"]["folder_id"] == lectures["id"]
    wrong = owner_api.post("/folders", {"course_id": other, "parent_id": lectures["id"], "name": "X"})
    assert wrong.status_code == 409 and wrong.json()["code"] == "different_course"
    assert owner_api.post("/folders", {"course_id": course, "name": "   "}).status_code == 422

    parent = week["id"]  # Lectures / Week 3-4 has 2 levels; build down to the limit of 5
    for name in ("L3", "L4", "L5"):
        parent = owner_api.post("/folders", {"course_id": course, "parent_id": parent, "name": name}).json()["id"]
    too_deep = owner_api.post("/folders", {"course_id": course, "parent_id": parent, "name": "L6"})
    assert too_deep.status_code == 422 and too_deep.json()["code"] == "folder_too_deep"

    cycle = owner_api.patch(f"/folders/{lectures['id']}", {"parent_id": week["id"]})
    assert cycle.status_code == 409 and cycle.json()["code"] == "folder_cycle"
    moved = owner_api.patch(f"/folders/{week['id']}", {"parent_id": None, "name": "Week 3"}).json()
    assert moved["parent_id"] is None and moved["path"] == "Week 3"
    listed = owner_api.get("/folders", course_id=course).json()
    assert [f["path"] for f in listed][:2] == ["Lectures", "Week 3"]
    assert owner_api.get("/folders", course_id=other).json() == []


def test_material_moves_into_folders_and_archiving_hides_it_but_keeps_it(owner_api: Api) -> None:
    course, other = _setup(owner_api)
    folder = owner_api.post("/folders", {"course_id": course, "name": "Lectures"}).json()
    pasted = owner_api.post(
        "/sources/text", {"course_id": course, "title": "Cells", "text": TEXT, "folder_id": folder["id"]}
    ).json()
    assert pasted["folder_id"] == folder["id"] and pasted["folder"] == "Lectures"
    loose = owner_api.upload(course, "notes.md", b"# Notes\n\nMitochondria make ATP.\n").json()
    run_pending()
    section = owner_api.sections(pasted["id"])[0]["id"]

    assert owner_api.post("/sources/move", {"source_ids": [loose["id"]], "folder_id": folder["id"]}).status_code == 200
    assert owner_api.get("/folders", course_id=course).json()[0]["files"] == 2
    elsewhere = owner_api.post("/folders", {"course_id": other, "name": "Misc"}).json()
    refused = owner_api.post("/sources/move", {"source_ids": [loose["id"]], "folder_id": elsewhere["id"]})
    assert refused.status_code == 409 and refused.json()["code"] == "different_course"
    assert owner_api.post("/sources/move", {"source_ids": [loose["id"]], "folder_id": None}).status_code == 200

    # Archive one file: hidden from the list and search, still readable and citable, restorable.
    r = owner_api.post("/sources/archive", {"source_ids": [loose["id"]], "archived": True})
    assert r.status_code == 200 and r.json()["sources"][0]["archived"] is True
    assert [s["id"] for s in owner_api.get("/sources", course_id=course).json()] == [pasted["id"]]
    assert len(owner_api.get("/sources", course_id=course, archived=True).json()) == 2
    assert owner_api.get("/sources/search", q="ATP").json()["hits"] == []
    assert owner_api.get(f"/sources/{loose['id']}").status_code == 200

    # Archive the folder: its files disappear too, but their sections stay readable for citations.
    assert owner_api.post(f"/folders/{folder['id']}/archive", {"archived": True}).json()["archived"] is True
    assert owner_api.get("/sources", course_id=course).json() == []
    assert owner_api.get("/sources/search", q="membrane").json()["hits"] == []
    assert owner_api.get(f"/sections/{section}").status_code == 200

    archived = owner_api.get("/library/archived").json()
    assert [f["name"] for f in archived["folders"]] == ["Lectures"]
    assert archived["folders"][0]["course"]["title"] == "Biology"
    assert [s["filename"] for s in archived["sources"]] == ["notes.md"]

    assert owner_api.post(f"/folders/{folder['id']}/archive", {"archived": False}).status_code == 200
    assert owner_api.post("/sources/archive", {"source_ids": [loose["id"]], "archived": False}).status_code == 200
    assert len(owner_api.get("/sources", course_id=course).json()) == 2
    assert owner_api.get("/sources/search", q="membrane").json()["hits"]
    assert owner_api.get("/library/archived").json()["sources"] == []

    # Only an empty folder can be removed.
    busy = _delete(owner_api, f"/folders/{folder['id']}")
    assert busy.status_code == 409 and busy.json()["code"] == "folder_not_empty"
    assert owner_api.post("/sources/move", {"source_ids": [pasted["id"]], "folder_id": None}).status_code == 200
    assert _delete(owner_api, f"/folders/{folder['id']}").status_code == 200
    assert owner_api.get("/folders", course_id=course).json() == []
    assert owner_api.get("/sources", course_id=course).json()[0]["folder"] is None


def test_archived_courses_and_groups_are_listed(owner_api: Api) -> None:
    course, _ = _setup(owner_api)
    group = owner_api.post("/groups", {"kind": "semester", "name": "Winter 2025"}).json()
    owner_api.patch(f"/courses/{course}", {"group_id": group["id"]})
    assert owner_api.post(f"/groups/{group['id']}/archive", {"archived": True}).status_code == 200
    archived = owner_api.get("/library/archived").json()
    assert [g["name"] for g in archived["groups"]] == ["Winter 2025"]
    assert [c["title"] for c in archived["courses"]] == ["Biology"]
    assert archived["courses"][0]["group_path"] == "Winter 2025"


def test_unknown_folders_and_material_are_not_reachable(owner_api: Api) -> None:
    course, _ = _setup(owner_api)
    stranger = str(uuid.uuid4())
    assert owner_api.post("/folders", {"course_id": stranger, "name": "X"}).status_code == 404
    assert owner_api.patch(f"/folders/{stranger}", {"name": "Y"}).status_code == 404
    assert owner_api.post("/sources/move", {"source_ids": [stranger], "folder_id": None}).status_code == 404
    assert owner_api.post("/sources/archive", {"source_ids": [stranger], "archived": True}).status_code == 404
    loose = owner_api.paste(course, TEXT).json()
    missing = owner_api.post("/sources/move", {"source_ids": [loose["id"]], "folder_id": stranger})
    assert missing.status_code == 404


def test_claude_imports_into_a_folder_by_path(owner_api: Api, conn: ConnectorApi) -> None:
    course, _ = _setup(owner_api)
    r = conn.post(
        "/sources/text", {"course_id": course, "title": "Week 3", "text": TEXT, "folder": "Lectures / Week 3"}
    )
    assert r.status_code == 201 and r.json()["folder"] == "Lectures / Week 3"
    headers = {**conn.auth, "Idempotency-Key": str(uuid.uuid4())}
    up = conn.client.post(
        "/api/v1/connector/sources",
        data={"course_id": course, "folder": "lectures/week 3"},
        files={"file": ("extra.md", b"# Extra\n\nMore.\n")},
        headers=headers,
    )
    assert up.status_code == 201 and up.json()["folder"] == "Lectures / Week 3"  # existing folders reused
    assert [f["path"] for f in owner_api.get("/folders", course_id=course).json()] == ["Lectures", "Lectures / Week 3"]
    outline = conn.get(f"/courses/{course}/outline").json()
    assert outline["folders"] == ["Lectures", "Lectures / Week 3"]
    assert {s["folder"] for s in outline["sources"]} == {"Lectures / Week 3"}
