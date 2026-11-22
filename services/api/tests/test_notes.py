"""Notes: autosave revisions, crash-safe acknowledgement, conflict preservation, offline replay (FR-03, T-10, T-19)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from recallspring_api import clock
from recallspring_api.main import create_app

from .conftest import Api, ConnectorApi, FrozenClock, make_user


def new_note(api: Api, body: str = "First draft", client_note_id: str | None = None) -> dict:
    cid = api.post("/courses", {"title": "Biology"}).json()["id"]
    r = api.post(
        "/notes",
        {"course_id": cid, "client_note_id": client_note_id or str(uuid.uuid4()), "title": "Glycolysis", "body": body},
    )
    assert r.status_code == 201
    return r.json()


def patch(api: Api, note_id: str, base: int, body: str, key: str | None = None):  # type: ignore[no-untyped-def]
    return api.client.patch(
        f"/api/v1/notes/{note_id}", json={"base_revision": base, "body": body}, headers=api.headers(key)
    )


def test_t19_acknowledged_autosave_survives_restart(owner_api: Api) -> None:
    body = "Glikoliza poteka v citoplazmi. 🧬 Pyruvate → mitochondria.\n\n  indented line"
    note = new_note(owner_api)
    saved = patch(owner_api, note["id"], 1, body)
    assert saved.status_code == 200 and saved.json()["revision"] == 2 and saved.json()["body"] == body

    with TestClient(create_app()) as restarted:  # simulated crash + reload on another tab
        api = Api(restarted)
        api.login("owner")
        stored = api.get(f"/notes/{note['id']}").json()
        assert stored["body"] == body and stored["revision"] == 2


def test_t10_conflicting_edits_return_409_and_keep_both_versions(owner_api: Api) -> None:
    note = new_note(owner_api)
    laptop = patch(owner_api, note["id"], 1, "Laptop version")
    assert laptop.status_code == 200

    stale = patch(owner_api, note["id"], 1, "Second-window version")
    assert stale.status_code == 409
    details = stale.json()["details"]
    assert stale.json()["code"] == "revision_conflict"
    assert details["current"]["body"] == "Laptop version" and details["current"]["revision"] == 2

    revisions = owner_api.get(f"/notes/{note['id']}/revisions").json()
    conflict = next(r for r in revisions if r["kind"] == "conflict")
    assert conflict["id"] == details["conflict_revision_id"]
    assert conflict["body"] == "Second-window version" and conflict["base_revision"] == 1
    assert owner_api.get(f"/notes/{note['id']}").json()["body"] == "Laptop version"  # no silent overwrite

    merged = patch(owner_api, note["id"], 2, "Laptop version + second-window version")
    assert merged.status_code == 200 and merged.json()["revision"] == 3


def test_replayed_conflict_does_not_duplicate_preserved_drafts(owner_api: Api) -> None:
    note = new_note(owner_api)
    patch(owner_api, note["id"], 1, "A")
    key = str(uuid.uuid4())
    first, again = patch(owner_api, note["id"], 1, "B", key=key), patch(owner_api, note["id"], 1, "B", key=key)
    assert first.status_code == again.status_code == 409 and first.json() == again.json()
    kinds = [r["kind"] for r in owner_api.get(f"/notes/{note['id']}/revisions").json()]
    assert kinds.count("conflict") == 1


def test_replayed_autosave_with_same_key_does_not_bump_revision(owner_api: Api) -> None:
    note = new_note(owner_api)
    key = str(uuid.uuid4())
    a, b = patch(owner_api, note["id"], 1, "Draft 2", key=key), patch(owner_api, note["id"], 1, "Draft 2", key=key)
    assert a.json()["revision"] == b.json()["revision"] == 2


def test_offline_created_note_replays_idempotently_by_client_note_id(owner_api: Api) -> None:
    client_note_id = str(uuid.uuid4())
    note = new_note(owner_api, client_note_id=client_note_id)
    again = owner_api.post(
        "/notes",
        {
            "course_id": note["course_id"],
            "client_note_id": client_note_id,
            "title": "Glycolysis",
            "body": "First draft",
        },
    )
    assert again.status_code == 200 and again.json()["id"] == note["id"]
    assert len(owner_api.get("/notes").json()) == 1


def test_autosave_history_is_coalesced_per_editing_burst(owner_api: Api, frozen: FrozenClock) -> None:
    note = new_note(owner_api)
    revision = 1
    for i in range(5):
        frozen.advance(seconds=5)
        revision = patch(owner_api, note["id"], revision, f"typing {i}").json()["revision"]
    frozen.advance(minutes=5)
    revision = patch(owner_api, note["id"], revision, "after a pause").json()["revision"]
    history = owner_api.get(f"/notes/{note['id']}/revisions").json()
    assert [(h["revision"], h["body"]) for h in history] == [(1, "First draft"), (6, "typing 4"), (7, "after a pause")]
    assert revision == 7


def test_notes_are_owner_scoped(owner_api: Api) -> None:
    note = new_note(owner_api)
    make_user("other")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        other.login("other")
        assert other.get(f"/notes/{note['id']}").status_code == 404
        assert patch(other, note["id"], 1, "hijack").status_code == 404
        assert other.get("/notes").json() == []


def test_note_lists_the_library_files_it_references(owner_api: Api, conn: ConnectorApi) -> None:
    from recallspring_api.db import new_session
    from recallspring_api.models import Source

    note = new_note(owner_api)
    cid = note["course_id"]
    pic = owner_api.paste(cid, "# Diagram\nA cell.", title="cell.md").json()
    sheet = owner_api.paste(cid, "# Sheet\nATP.", title="atp.md").json()
    body = (
        f"See ![cell](source:{pic['id']}) and [the sheet](source:{sheet['id']}), again [sheet](source:{sheet['id']}).\n"
        f"[gone](source:{uuid.uuid4()})"
    )
    saved = patch(owner_api, note["id"], 1, body).json()
    refs = saved["references"]
    assert [r["id"] for r in refs[:2]] == [pic["id"], sheet["id"]] and len(refs) == 3  # first appearance, unique
    assert refs[0]["filename"] == pic["filename"] and refs[0]["missing"] is False
    assert refs[2] == {"id": refs[2]["id"], "filename": None, "kind": None, "course_id": None, "missing": True}
    assert owner_api.get("/notes").json()[0]["references"] == refs

    with new_session() as db:  # a file deleted later shows as missing, the note text is untouched
        db.get(Source, uuid.UUID(sheet["id"])).deleted_at = clock.now()
        db.commit()
    again = owner_api.get(f"/notes/{note['id']}").json()
    assert again["body"] == body and [r["missing"] for r in again["references"]] == [False, True, True]

    # Claude and ChatGPT get the names and IDs, so they can open the files.
    seen = conn.get("/notes", course_id=cid).json()[0]["references"]
    assert seen[0] == {"source_id": pic["id"], "filename": pic["filename"], "kind": pic["kind"], "missing": False}


def test_references_to_another_learners_file_reveal_nothing(owner_api: Api) -> None:
    make_user("other")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        other.login("other")
        course = other.post("/courses", {"title": "Secret"}).json()
        secret = other.paste(course["id"], "# Private\nx", title="private.md").json()
    note = new_note(owner_api)
    saved = patch(owner_api, note["id"], 1, f"![x](source:{secret['id']})").json()
    assert saved["references"][0]["missing"] is True and saved["references"][0]["filename"] is None


def test_delete_note_is_confirmed_soft_and_restorable(owner_api: Api, frozen: FrozenClock) -> None:
    from sqlalchemy import select

    from recallspring_api.db import new_session
    from recallspring_api.models import AuditEvent

    note = new_note(owner_api, body="Keep me")
    key = str(uuid.uuid4())
    gone = owner_api.client.delete(f"/api/v1/notes/{note['id']}", headers=owner_api.headers(key))
    assert gone.status_code == 200 and gone.json()["restorable_days"] == 30
    assert gone.json()["deleted"]["deleted_at"] is not None
    replay = owner_api.client.delete(f"/api/v1/notes/{note['id']}", headers=owner_api.headers(key))
    assert replay.status_code == 200 and replay.headers.get("Idempotent-Replay") == "true"

    assert owner_api.get("/notes").json() == []
    assert owner_api.get(f"/notes/{note['id']}").status_code == 404
    assert owner_api.get(f"/notes/{note['id']}/revisions").status_code == 404
    assert patch(owner_api, note["id"], 1, "edit after delete").status_code == 404
    again = owner_api.client.delete(f"/api/v1/notes/{note['id']}", headers=owner_api.headers())
    assert again.status_code == 404
    deleted = owner_api.get("/notes/deleted").json()
    assert [d["id"] for d in deleted] == [note["id"]] and deleted[0]["body"] == "Keep me"

    restored = owner_api.post(f"/notes/{note['id']}/restore")
    assert restored.status_code == 200 and restored.json()["deleted_at"] is None
    assert owner_api.get(f"/notes/{note['id']}").json()["body"] == "Keep me"
    assert owner_api.get("/notes/deleted").json() == []
    with new_session() as db:
        actions = [a.action for a in db.scalars(select(AuditEvent).where(AuditEvent.target_type == "note"))]
    assert actions.count("note.deleted") == 1 and actions.count("note.restored") == 1

    # After 30 days the note can no longer be restored from the app (it stays in the database and backups).
    owner_api.client.delete(f"/api/v1/notes/{note['id']}", headers=owner_api.headers())
    frozen.advance(days=31)
    assert owner_api.get("/notes/deleted").json() == []
    assert owner_api.post(f"/notes/{note['id']}/restore").status_code == 404


def test_deleting_or_restoring_another_learners_note_is_not_found(owner_api: Api) -> None:
    note = new_note(owner_api)
    make_user("other")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        other.login("other")
        assert other.client.delete(f"/api/v1/notes/{note['id']}", headers=other.headers()).status_code == 404
        assert other.post(f"/notes/{note['id']}/restore").status_code == 404
        assert other.get("/notes/deleted").json() == []
    assert owner_api.get(f"/notes/{note['id']}").status_code == 200


def test_deleted_notes_leave_the_assistants_view(owner_api: Api, conn: ConnectorApi) -> None:
    note = new_note(owner_api, body="Hidden after delete")
    owner_api.client.delete(f"/api/v1/notes/{note['id']}", headers=owner_api.headers())
    assert conn.get("/notes", course_id=note["course_id"]).json() == []
