# ruff: noqa: F811 (the tool_fake fixture is a test argument)
"""Chat folders, plain chats and ghost chats (ADR-012 §4-5)."""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from recallspring_api.db import new_session
from recallspring_api.main import create_app
from recallspring_api.models import AiConversation, AiGhostUsage, AiMessage, AuditEvent

from .conftest import Api, make_user
from .test_chatgpt_signin import reply_events, sign_in
from .test_chatgpt_tools import ToolFake, calls, outputs
from .test_chatgpt_tools import fake as tool_fake  # noqa: F401 (fixture)


def folders(api: Api) -> list[dict[str, Any]]:
    return api.get("/ai/chatgpt/conversations").json()["folders"]


def new_folder(api: Api, name: str, **extra: Any) -> dict[str, Any]:
    r = api.post("/ai/chatgpt/folders", {"name": name, **extra})
    assert r.status_code == 200, r.text
    return next(f for f in r.json()["folders"] if f["name"] == name)


def chat(api: Api, fake: ToolFake, text: str, n: int, **extra: Any) -> dict[str, Any]:
    fake.rounds = [reply_events(f"Reply {n}", n)]
    r = api.post("/ai/chatgpt/messages", {"model": "gpt-test", "message": text, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def ghost(api: Api, body: dict[str, Any]) -> tuple[Any, list[dict[str, Any]]]:
    r = api.client.post("/api/v1/ai/chatgpt/ghost/stream", json=body, headers=api.headers())
    events = [json.loads(line) for line in r.text.splitlines() if line.strip()] if r.status_code == 200 else []
    return r, events


def counts() -> tuple[int, int, int]:
    with new_session() as db:
        return (
            db.scalar(select(func.count()).select_from(AiConversation)) or 0,
            db.scalar(select(func.count()).select_from(AiMessage)) or 0,
            db.scalar(select(func.count()).select_from(AiGhostUsage)) or 0,
        )


# ---------------------------------------------------------------- folders


def test_folders_one_level_deep_sorted_pinned_first(owner_api: Api) -> None:
    top = new_folder(owner_api, "statistics", icon="function", color="#185FA5")
    sub = new_folder(owner_api, "Midterm 1", parent_id=top["id"])
    assert sub["parent_id"] == top["id"] and top["color"] == "#185fa5" and top["icon"] == "function"

    r = owner_api.post("/ai/chatgpt/folders", {"name": "Too deep", "parent_id": sub["id"]})
    assert r.status_code == 422 and r.json()["code"] == "folder_too_deep"
    r = owner_api.post("/ai/chatgpt/folders", {"name": "X", "icon": "<script>"})
    assert r.status_code == 422 and r.json()["code"] == "unknown_icon"
    r = owner_api.post("/ai/chatgpt/folders", {"name": "X", "color": "red"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_color"

    other = new_folder(owner_api, "Biology")
    pinned = new_folder(owner_api, "Zoo", pinned=True)
    # pinned first, then by name ignoring case; each subfolder right under its parent
    assert [f["name"] for f in folders(owner_api)] == ["Zoo", "Biology", "statistics", "Midterm 1"]

    # a folder with subfolders cannot become a subfolder; one without can
    r = owner_api.patch(f"/ai/chatgpt/folders/{top['id']}", {"parent_id": other["id"]})
    assert r.status_code == 422 and r.json()["code"] == "folder_too_deep"
    r = owner_api.patch(f"/ai/chatgpt/folders/{pinned['id']}", {"parent_id": other["id"], "pinned": False})
    assert r.status_code == 200
    moved = next(f for f in r.json()["folders"] if f["id"] == pinned["id"])
    assert moved["parent_id"] == other["id"] and moved["pinned"] is False


def test_moving_and_deleting_never_deletes_conversations(owner_api: Api, tool_fake: ToolFake) -> None:
    fake = tool_fake
    sign_in(owner_api, fake)
    top = new_folder(owner_api, "Course A")
    sub = new_folder(owner_api, "Old chats", parent_id=top["id"])
    other_sub = new_folder(owner_api, "Notes", parent_id=top["id"])
    a = chat(owner_api, fake, "First", 1)
    b = chat(owner_api, fake, "Second", 2)

    r = owner_api.put(f"/ai/chatgpt/conversations/{a['id']}/folder", {"folder_id": sub["id"]})
    assert r.status_code == 200
    moved = next(c for c in r.json()["conversations"] if c["id"] == a["id"])
    assert moved["updated_at"] == a["updated_at"]  # filing is not activity: the list order stays
    owner_api.put(f"/ai/chatgpt/conversations/{b['id']}/folder", {"folder_id": top["id"]})
    listed = {c["id"]: c["folder_id"] for c in owner_api.get("/ai/chatgpt/conversations").json()["conversations"]}
    assert listed == {a["id"]: sub["id"], b["id"]: top["id"]}
    assert {f["name"]: f["conversations"] for f in folders(owner_api)} == {"Course A": 1, "Old chats": 1, "Notes": 0}

    # deleting a subfolder: its conversations go to the parent
    r = owner_api.client.delete(f"/api/v1/ai/chatgpt/folders/{sub['id']}", headers=owner_api.headers())
    assert r.status_code == 200
    assert {c["id"]: c["folder_id"] for c in r.json()["conversations"]} == {a["id"]: top["id"], b["id"]: top["id"]}

    # deleting a top-level folder: conversations to "No folder", subfolders up to the top level
    r = owner_api.client.delete(f"/api/v1/ai/chatgpt/folders/{top['id']}", headers=owner_api.headers())
    body = r.json()
    assert {c["folder_id"] for c in body["conversations"]} == {None} and len(body["conversations"]) == 2
    assert [(f["name"], f["parent_id"]) for f in body["folders"]] == [("Notes", None)]
    assert other_sub["id"] == body["folders"][0]["id"]
    with new_session() as db:
        audit = db.scalar(
            select(AuditEvent).where(AuditEvent.action == "chat_folder.deleted").order_by(AuditEvent.occurred_at.desc())
        )
        assert audit is not None and sorted(audit.details["conversation_ids"]) == sorted([a["id"], b["id"]])

    r = owner_api.put(f"/ai/chatgpt/conversations/{a['id']}/folder", {"folder_id": top["id"]})
    assert r.status_code == 404  # a deleted folder takes nothing


def test_a_course_conversation_files_itself_only_with_exactly_one_linked_folder(
    owner_api: Api, tool_fake: ToolFake
) -> None:
    fake = tool_fake
    sign_in(owner_api, fake)
    course = owner_api.course_with_question()["course_id"]
    linked = new_folder(owner_api, "Biology chats", course_id=course)
    assert linked["course"] == {"id": course, "title": "Biology 101"}

    first = chat(owner_api, fake, "Study", 1, recallspring=False, course_id=course)
    assert first["folder_id"] == linked["id"]

    new_folder(owner_api, "Also biology", course_id=course)
    second = chat(owner_api, fake, "Study again", 2, recallspring=False, course_id=course)
    assert second["folder_id"] is None  # two linked folders: the learner files it


def test_other_learners_cannot_see_or_use_folders(owner_api: Api) -> None:
    mine = new_folder(owner_api, "Mine")
    make_user("intruder")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        assert other.login("intruder").status_code == 200
        assert other.get("/ai/chatgpt/conversations").json()["folders"] == []
        assert other.patch(f"/ai/chatgpt/folders/{mine['id']}", {"name": "Taken"}).status_code == 404
        assert other.post("/ai/chatgpt/folders", {"name": "Sub", "parent_id": mine["id"]}).status_code == 404
        r = other.client.delete(f"/api/v1/ai/chatgpt/folders/{mine['id']}", headers=other.headers())
        assert r.status_code == 404
    assert [f["name"] for f in folders(owner_api)] == ["Mine"]


# ---------------------------------------------------------------- plain chats


def test_a_plain_chat_never_gets_a_course_or_tools(owner_api: Api, tool_fake: ToolFake) -> None:
    fake = tool_fake
    sign_in(owner_api, fake)
    course = owner_api.course_with_question()["course_id"]
    conv = chat(owner_api, fake, "Just talk", 1, plain=True, recallspring=True, course_id=course)
    assert conv["plain"] is True and conv["course"] is None
    assert "tools" not in fake.bodies()[-1]
    again = chat(owner_api, fake, "More", 2, conversation_id=conv["id"], recallspring=True)
    assert again["plain"] is True and "tools" not in fake.bodies()[-1]
    listed = owner_api.get("/ai/chatgpt/conversations").json()["conversations"]
    assert listed[0]["plain"] is True


# ---------------------------------------------------------------- ghost chats


def test_a_ghost_chat_keeps_nothing_but_token_usage(owner_api: Api, tool_fake: ToolFake) -> None:
    fake = tool_fake
    sign_in(owner_api, fake)
    before = counts()
    fake.rounds = [reply_events("Ghostly hello", 1)]
    secret = "my very private question"
    r, events = ghost(owner_api, {"model": "gpt-test", "turns": [{"role": "user", "text": secret}], "plain": True})
    assert r.status_code == 200, r.text
    assert [e["type"] for e in events] == ["text", "text", "done"]  # nothing "saved"
    reply = events[-1]["reply"]
    assert reply["text"] == "Ghostly hello" and reply["model"] == "gpt-test-2026-11-01"
    assert reply["usage"]["total_tokens"] == 52
    body = fake.bodies()[-1]
    assert body["store"] is False and body["stream"] is True and "tools" not in body

    after = counts()
    assert after[:2] == before[:2] and after[2] == before[2] + 1
    with new_session() as db:
        row = db.scalar(select(AiGhostUsage))
        assert row is not None and row.outcome == "completed" and "secret" not in (row.usage or {})
        dumped = json.dumps([a.details for a in db.scalars(select(AuditEvent))], default=str)
        assert secret not in dumped and "Ghostly" not in dumped
    usage = owner_api.get("/ai/chatgpt/conversations").json()["usage"]
    assert usage["last_24_hours"]["replies"] == 1 and usage["last_24_hours"]["total_tokens"] == 52

    # the page sends the whole history; the server answers from it
    fake.rounds = [reply_events("Second", 2)]
    turns = [
        {"role": "user", "text": secret},
        {"role": "assistant", "text": "Ghostly hello"},
        {"role": "user", "text": "And then?"},
    ]
    r, events = ghost(owner_api, {"model": "gpt-test", "turns": turns, "plain": True})
    assert events[-1]["type"] == "done"
    sent = [i for i in fake.bodies()[-1]["input"] if i.get("type") == "message"]
    assert len(sent) == 3
    assert counts()[:2] == before[:2]


def test_a_ghost_chat_only_reads_recallspring(owner_api: Api, tool_fake: ToolFake) -> None:
    fake = tool_fake
    sign_in(owner_api, fake)
    ids = owner_api.course_with_question()
    before = counts()
    fake.rounds = [
        calls(
            1,
            ("c1", "get_course_outline", {"course_id": ids["course_id"]}),
            ("c2", "create_questions", {"course_id": ids["course_id"], "questions": []}),
        ),
        reply_events("Read it.", 2),
    ]
    body = {"model": "gpt-test", "turns": [{"role": "user", "text": "What is in it?"}], "course_id": ids["course_id"]}
    r, events = ghost(owner_api, body)
    assert r.status_code == 200, r.text
    steps = [e["step"] for e in events if e["type"] == "step"]
    assert [(s["name"], s["status"], s["error_code"]) for s in steps] == [
        ("get_course_outline", "ok", None),
        ("create_questions", "error", "read_only"),
    ]
    assert all(s["arguments"] is None for s in steps)
    first = fake.bodies()[0]
    names = {t["name"] for t in first["tools"][0]["tools"]}
    assert "get_course_outline" in names and "create_questions" not in names and "open_answer_form" not in names
    assert "ghost chat" in first["instructions"] and "Biology 101" in first["instructions"]
    assert outputs(fake.bodies()[1])["c1"]["ok"] is True
    assert counts()[:2] == before[:2]
    assert events[-1]["reply"]["steps"][0]["name"] == "get_course_outline"


def test_ghost_errors_say_so_and_never_fall_back(owner_api: Api, tool_fake: ToolFake) -> None:
    fake = tool_fake
    r, _ = ghost(owner_api, {"model": "gpt-test", "turns": [{"role": "user", "text": "Hi"}]})
    assert r.status_code == 409  # not signed in
    sign_in(owner_api, fake)
    r, _ = ghost(owner_api, {"model": "gpt-test", "turns": [{"role": "assistant", "text": "Hi"}]})
    assert r.status_code == 422  # the last turn is the learner's
    fake.rounds = [(429, {"error": {"code": "subscription_sharing_usage_limit_exceeded"}})]
    r, events = ghost(owner_api, {"model": "gpt-test", "turns": [{"role": "user", "text": "Hi"}], "plain": True})
    assert events[-1]["type"] == "error" and events[-1]["code"] == "chatgpt_usage_limit"
    assert counts()[:2] == (0, 0)


def test_keep_this_chat_turns_a_ghost_into_a_saved_conversation(owner_api: Api, tool_fake: ToolFake) -> None:
    fake = tool_fake
    sign_in(owner_api, fake)
    course = owner_api.course_with_question()["course_id"]
    linked = new_folder(owner_api, "Biology chats", course_id=course)
    turns = [
        {"role": "user", "text": "Explain osmosis"},
        {"role": "assistant", "text": "Osmosis is…", "model": "gpt-test-2026-11-01"},
    ]
    r = owner_api.post("/ai/chatgpt/ghost/keep", {"turns": turns, "course_id": course})
    assert r.status_code == 200, r.text
    conv = r.json()
    assert conv["title"] == "Explain osmosis" and conv["course"]["id"] == course
    assert conv["folder_id"] == linked["id"]
    assert [(m["role"], m["text"], m["model"]) for m in conv["messages"]] == [
        ("user", "Explain osmosis", None),
        ("assistant", "Osmosis is…", "gpt-test-2026-11-01"),
    ]
    # from now on it is a normal conversation
    fake.rounds = [reply_events("Go on.", 3)]
    r = owner_api.post("/ai/chatgpt/messages", {"model": "gpt-test", "message": "More", "conversation_id": conv["id"]})
    assert r.status_code == 200 and len(r.json()["messages"]) == 4
