"""Notes: autosave revisions, crash-safe acknowledgement, conflict preservation, offline replay (FR-03, T-10, T-19)."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from recallspring_api.main import create_app

from .conftest import Api, FrozenClock, make_user


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
