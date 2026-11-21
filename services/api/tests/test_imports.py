"""Moving in: a ChatGPT data export (chats saved word for word, attached files, custom instructions offered as
study preferences), ZIPs of material with their folders, and uploaded folders."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from typing import Any

from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.ingest.jobs import run_pending
from recallspring_api.models import AuditEvent, User
from recallspring_api.services import chatgpt_import

from .conftest import Api, ConnectorApi, FrozenClock

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
T0 = 1_772_000_000.0  # 2026-02-25
HIDDEN = {"is_visually_hidden_from_conversation": True}
MEMORY = "Studies biology; prefers questions first."


def _delete(api: Api, path: str) -> Any:
    return api.client.delete(f"/api/v1{path}", headers=api.headers())


def _msg(mid: str, role: str, text: str | None, t: float, **extra: Any) -> dict[str, Any]:
    content = extra.pop("content", None) or {"content_type": "text", "parts": [text]}
    return {
        "id": mid,
        "author": {"role": role},
        "create_time": t,
        "content": content,
        "recipient": extra.pop("recipient", "all"),
        "metadata": extra.pop("metadata", {}),
    }


def _chain(nodes: list[tuple[str, dict[str, Any] | None]], extra: dict[str, Any] | None = None) -> dict[str, Any]:
    mapping: dict[str, Any] = {}
    parent = None
    for node_id, message in nodes:
        mapping[node_id] = {"id": node_id, "message": message, "parent": parent, "children": []}
        if parent:
            mapping[parent]["children"].append(node_id)
        parent = node_id
    for node_id, (parent_id, message) in (extra or {}).items():
        mapping[node_id] = {"id": node_id, "message": message, "parent": parent_id, "children": []}
        mapping[parent_id]["children"].append(node_id)
    return mapping


def export_zip() -> bytes:
    krebs = {
        "id": "conv-krebs",
        "title": "Krebs cycle",
        "create_time": T0,
        "update_time": T0 + 600,
        "mapping": _chain(
            [
                ("root", None),
                ("sys", _msg("sys", "system", "You are ChatGPT", T0, metadata=HIDDEN)),
                (
                    "ctx",
                    _msg(
                        "ctx",
                        "user",
                        None,
                        T0,
                        content={
                            "content_type": "user_editable_context",
                            "user_profile": "About the user:\n```I study biology in Ljubljana.```",
                            "user_instructions": "How to respond:\n```Ask me questions before explaining.```",
                        },
                    ),
                ),
                (
                    "u1",
                    _msg(
                        "u1",
                        "user",
                        None,
                        T0 + 10,
                        content={
                            "content_type": "multimodal_text",
                            "parts": [
                                {"content_type": "image_asset_pointer", "asset_pointer": "file-service://file-img1"},
                                "Explain the Krebs cycle from my notes.",
                            ],
                        },
                        metadata={
                            "attachments": [
                                {"id": "file-img1", "name": "board.png"},
                                {"id": "file-abc123", "name": "notes.md"},
                                {"id": "file-gone", "name": "missing.pdf"},
                            ]
                        },
                    ),
                ),
                ("bio", _msg("bio", "assistant", MEMORY, T0 + 20, recipient="bio")),
                ("tool", _msg("tool", "tool", "Model set context updated.", T0 + 21)),
                ("a1", _msg("a1", "assistant", "The Krebs cycle oxidises acetyl-CoA to CO2.", T0 + 30)),
            ],
            extra={"a1-old": ("u1", _msg("a1-old", "assistant", "An earlier answer that was regenerated.", T0 + 25))},
        ),
        "current_node": "a1",
    }
    physics = {
        "conversation_id": "conv-physics",
        "title": "Newton's laws",
        "create_time": T0 + 86_400,
        "update_time": T0 + 90_000,
        "gizmo_id": "g-p-abc",
        "mapping": _chain([("r", None), ("q", _msg("q", "user", "What is inertia?", T0 + 86_400))]),
        "current_node": "q",
    }
    empty = {"id": "conv-empty", "title": "Nothing", "mapping": _chain([("r", None)]), "current_node": "r"}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("conversations.json", json.dumps([krebs, physics, empty]))
        zf.writestr("chat.html", "<script>alert(1)</script>")
        zf.writestr("user.json", json.dumps({"id": "user-1"}))
        zf.writestr("file-abc123-notes.md", "# My notes\n\nAcetyl-CoA enters the cycle.\n")
        zf.writestr("file-img1-board.png", PNG)
    return buf.getvalue()


def _stage(api: Api, content: bytes, name: str = "chatgpt-export.zip") -> Any:
    return api.client.post(
        "/api/v1/imports/chatgpt", files={"file": (name, content, "application/zip")}, headers=api.headers()
    )


def _audits(action: str) -> list[AuditEvent]:
    with new_session() as db:
        return list(db.scalars(select(AuditEvent).where(AuditEvent.action == action)))


def test_chatgpt_export_is_staged_and_chosen_chats_are_saved_word_for_word(owner_api: Api) -> None:
    course = owner_api.post("/courses", {"title": "Biochemistry"}).json()["id"]
    staged = _stage(owner_api, export_zip())
    assert staged.status_code == 201, staged.text
    view = staged.json()
    assert [c["title"] for c in view["conversations"]] == ["Newton's laws", "Krebs cycle"]  # newest first
    assert view["skipped"] == 1  # the chat without messages
    assert view["instructions"] == {
        "about_you": "I study biology in Ljubljana.",
        "how_to_respond": "Ask me questions before explaining.",
    }
    assert view["memories"] == ["Studies biology; prefers questions first."]
    assert view["projects"] == [{"id": "g-p-abc", "chats": 1}]
    krebs = next(c for c in view["conversations"] if c["key"] == "conv-krebs")
    assert krebs["messages"] == 2 and krebs["files"] == 2 and krebs["files_missing"] == 1 and krebs["saved"] is None
    assert owner_api.get("/sources").json() == []  # nothing is in the library yet

    text = owner_api.get(f"/imports/chatgpt/{view['id']}/chats/conv-krebs").json()["text"]
    assert text.startswith("# Krebs cycle\n")
    assert "## You · 2026-02-25" in text and "## ChatGPT · 2026-02-25" in text
    assert "[Image: board.png]\n\nExplain the Krebs cycle from my notes." in text
    assert "Attached: board.png, notes.md, missing.pdf" in text
    assert "oxidises acetyl-CoA" in text
    for left_out in ("regenerated", "Model set context", "You are ChatGPT", "prefers questions first"):
        assert left_out not in text

    saved = owner_api.post(
        f"/imports/chatgpt/{view['id']}/save",
        {"course_id": course, "keys": ["conv-krebs"], "folder": "Chats from ChatGPT"},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["conversations"] == 1 and body["skipped"] == []
    by_name = {s["filename"]: s for s in body["imported"]}
    assert set(by_name) == {"Krebs cycle.md", "notes.md", "board.png"}
    chat = by_name["Krebs cycle.md"]
    assert chat["category"] == "chat" and chat["origin"] == "import" and chat["folder"] == "Chats from ChatGPT"
    assert by_name["notes.md"]["origin"] == "import" and by_name["board.png"]["kind"] == "image"
    run_pending()
    headings = [s["heading"] or "" for s in owner_api.sections(chat["id"])]
    assert any(h.endswith("You · 2026-02-25 07:13") for h in headings), headings

    again = owner_api.post(
        f"/imports/chatgpt/{view['id']}/save",
        {"course_id": course, "keys": ["conv-krebs"], "folder": "chats from chatgpt"},
    ).json()
    assert again["imported"] == [] and {s["reason"] for s in again["skipped"]} == {"already in this folder"}
    listed = owner_api.get(f"/imports/chatgpt/{view['id']}").json()
    assert next(c for c in listed["conversations"] if c["key"] == "conv-krebs")["saved"]["source_id"] == chat["id"]
    assert owner_api.get("/imports/chatgpt").json()[0]["saved"] == 1
    assert len(_audits("import.chatgpt_staged")) == 1 and len(_audits("import.chatgpt_saved")) == 2

    unknown = owner_api.post(f"/imports/chatgpt/{view['id']}/save", {"course_id": course, "keys": ["nope"]})
    assert unknown.status_code == 404
    assert owner_api.get(f"/imports/chatgpt/{view['id']}/chats/..%2Findex").status_code == 404

    assert _delete(owner_api, f"/imports/chatgpt/{view['id']}").status_code == 200
    assert owner_api.get(f"/imports/chatgpt/{view['id']}").status_code == 404
    assert owner_api.get("/imports/chatgpt").json() == []
    assert owner_api.get(f"/sources/{chat['id']}").status_code == 200  # saved chats stay
    assert len(_audits("import.chatgpt_discarded")) == 1


def test_uploads_that_are_not_chatgpt_exports_are_refused(owner_api: Api) -> None:
    not_zip = _stage(owner_api, b"hello")
    assert not_zip.status_code == 422 and not_zip.json()["code"] == "not_a_zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("slides.md", "# Slides\n")
    other = _stage(owner_api, buf.getvalue())
    assert other.status_code == 422 and other.json()["code"] == "not_a_chatgpt_export"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("conversations.json", '{"not": "a list"}')
    bad = _stage(owner_api, buf.getvalue())
    assert bad.status_code == 422 and bad.json()["code"] == "not_a_chatgpt_export"
    assert owner_api.get("/imports/chatgpt").json() == []


def test_staged_exports_expire(owner_api: Api, frozen: FrozenClock) -> None:
    view = _stage(owner_api, export_zip()).json()
    assert len(owner_api.get("/imports/chatgpt").json()) == 1
    frozen.advance(days=8)  # past the retention (and the login session), so the service is called directly
    with new_session() as db:
        user = db.scalar(select(User))
        assert user is not None
        assert chatgpt_import.list_imports(user) == []
        assert (chatgpt_import._dir(user.id, uuid.UUID(view["id"])) / "export.zip").is_file()  # until removed
        assert chatgpt_import.expire(db, user) == 1
        db.commit()
        assert not chatgpt_import._dir(user.id, uuid.UUID(view["id"])).exists()
    assert len(_audits("import.chatgpt_expired")) == 1


def test_study_preferences_are_kept_and_given_to_claude(owner_api: Api, conn: ConnectorApi) -> None:
    course = owner_api.post("/courses", {"title": "Biochemistry"}).json()["id"]
    assert owner_api.get("/settings/preferences").json()["text"] == ""
    assert conn.get(f"/courses/{course}/context").json()["learner_preferences"] is None
    text = "  Ask me questions before explaining.  "
    put = owner_api.client.put("/api/v1/settings/preferences", json={"text": text}, headers=owner_api.headers())
    assert put.status_code == 200 and put.json()["text"] == "Ask me questions before explaining."
    prefs = conn.get(f"/courses/{course}/context").json()["learner_preferences"]
    assert prefs["text"] == "Ask me questions before explaining." and "never override" in prefs["how_to_use"]
    long = owner_api.client.put("/api/v1/settings/preferences", json={"text": "x" * 4001}, headers=owner_api.headers())
    assert long.status_code == 422
    cleared = owner_api.client.put("/api/v1/settings/preferences", json={"text": " "}, headers=owner_api.headers())
    assert cleared.json()["text"] == ""
    assert len(_audits("study.preferences_changed")) == 2


def _zip(entries: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _upload_zip(api: Api, course: str, content: bytes, folder_id: str | None = None) -> Any:
    data = {"course_id": course, **({"folder_id": folder_id} if folder_id else {})}
    return api.client.post(
        "/api/v1/sources/zip", data=data, files={"file": ("material.zip", content)}, headers=api.headers()
    )


def test_a_zip_of_material_keeps_its_folders_and_skips_what_does_not_fit(owner_api: Api) -> None:
    course = owner_api.post("/courses", {"title": "Biology"}).json()["id"]
    base = owner_api.post("/folders", {"course_id": course, "name": "Imported"}).json()
    content = _zip(
        {
            "Week 1/slides.md": "# Slides\n\nCells.\n",
            "Week 1/notes.txt": "Membranes.\n",
            "Week 2/Sub/exercise.md": "# Exercise\n\nSolve it.\n",
            "Week 2/photo.png": PNG,
            "Week 2/fake.png": b"not a png",
            "__MACOSX/Week 1/._slides.md": "junk",
            ".git/config": "x",
            "../evil.md": "# Evil\n",
            "setup.exe": b"MZ",
            "old.doc": b"\xd0\xcf\x11\xe0",
        }
    )
    r = _upload_zip(owner_api, course, content, base["id"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert {(s["filename"], s["folder"]) for s in body["imported"]} == {
        ("slides.md", "Imported / Week 1"),
        ("notes.txt", "Imported / Week 1"),
        ("exercise.md", "Imported / Week 2 / Sub"),
        ("photo.png", "Imported / Week 2"),
    }
    reasons = {s["name"]: s["reason"] for s in body["skipped"]}
    assert reasons == {
        "Week 2/fake.png": "the content does not match the file type",
        "setup.exe": "this type of file is not supported",
        "old.doc": "old Office format; save it as .docx/.pptx/.xlsx",
    }
    assert len(_audits("source.zip_imported")) == 1

    again = _upload_zip(owner_api, course, content, base["id"]).json()
    assert again["imported"] == [] and len(again["skipped"]) == 7
    assert not_zip(owner_api, course).json()["code"] == "not_a_zip"


def not_zip(api: Api, course: str) -> Any:
    return _upload_zip(api, course, b"plain text")


def test_uploaded_folders_and_deep_zips_fit_the_folder_limit(owner_api: Api) -> None:
    course = owner_api.post("/courses", {"title": "Biology"}).json()["id"]
    parent = None
    for name in ("A", "B", "C", "D"):
        body = {"course_id": course, "name": name, **({"parent_id": parent} if parent else {})}
        parent = owner_api.post("/folders", body).json()["id"]
    r = _upload_zip(owner_api, course, _zip({"x/y/z/deep.md": "# Deep\n"}), parent)
    assert r.json()["imported"][0]["folder"] == "A / B / C / D / x - y - z"

    top = owner_api.post("/folders", {"course_id": course, "name": "Lectures"}).json()["id"]
    up = owner_api.client.post(
        "/api/v1/sources",
        data={"course_id": course, "folder_id": top, "folder_path": "Week 3/Slides"},
        files={"file": ("intro.md", b"# Intro\n")},
        headers=owner_api.headers(),
    )
    assert up.status_code == 201 and up.json()["folder"] == "Lectures / Week 3 / Slides"
    missing = owner_api.client.post(
        "/api/v1/sources",
        data={"course_id": course, "folder_id": str(uuid.uuid4()), "folder_path": "X"},
        files={"file": ("intro.md", b"# Intro\n")},
        headers=owner_api.headers(),
    )
    assert missing.status_code == 404
