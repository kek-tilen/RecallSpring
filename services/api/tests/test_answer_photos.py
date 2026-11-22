"""Photos of work solved on paper: saved first in the Library, linked to the answer or Chat message, checked
(own images, same course, at most 4), and shown to the assistants that grade or reply."""

from __future__ import annotations

import uuid
from typing import Any

from .conftest import Api, ConnectorApi
from .office import PNG_1PX
from .test_chatgpt_signin import reply_events, sign_in
from .test_chatgpt_tools import ToolFake, calls, fake, send  # noqa: F401 - fixture

_ = fake


def photo(api: Api, course_id: str, name: str = "answer.png") -> str:
    r = api.client.post(
        "/api/v1/sources",
        data={"course_id": course_id, "category": "notes", "folder_path": "Answer photos"},
        files={"file": (name, PNG_1PX)},
        headers=api.headers(),
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def answer(api: Api, question_id: str, text: str = "", photo_ids: list[str] | None = None) -> Any:
    rid = str(uuid.uuid4())
    body = {"question_id": question_id, "client_request_id": rid, "answer_text": text, "photo_ids": photo_ids or []}
    return api.post("/attempts", body, key=rid)


def test_a_photo_alone_is_an_answer_and_every_assistant_gets_it(owner_api: Api, conn: ConnectorApi) -> None:
    ids = owner_api.course_with_question()
    pid = photo(owner_api, ids["course_id"])
    folder = owner_api.get("/folders", course_id=ids["course_id"]).json()
    assert [f["name"] for f in folder] == ["Answer photos"]

    assert answer(owner_api, ids["question_id"]).json()["code"] == "answer_empty"
    saved = answer(owner_api, ids["question_id"], photo_ids=[pid, pid])
    assert saved.status_code == 201, saved.text
    attempt = owner_api.get(f"/attempts/{saved.json()['attempt_id']}").json()
    assert attempt["answer_text"] == "" and attempt["photos"] == [
        {"id": pid, "filename": "answer.png", "available": True}
    ]
    graded_view = conn.get(f"/attempts/{attempt['id']}").json()
    assert graded_view["photos"][0]["id"] == pid
    assert conn.get(f"/sources/{pid}/image").status_code == 200


def test_only_own_images_from_the_same_course_and_at_most_four(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    other = owner_api.post("/courses", {"title": "Chemistry"}).json()
    elsewhere = photo(owner_api, other["id"])
    text = owner_api.paste(ids["course_id"], "# Notes\n\nSome text that is long enough to be a section.").json()
    assert answer(owner_api, ids["question_id"], "x", [elsewhere]).json()["code"] == "photo_other_course"
    assert answer(owner_api, ids["question_id"], "x", [text["id"]]).json()["code"] == "photo_invalid"
    assert answer(owner_api, ids["question_id"], "x", [str(uuid.uuid4())]).json()["code"] == "photo_invalid"
    five = [photo(owner_api, ids["course_id"], f"p{i}.png") for i in range(5)]
    assert answer(owner_api, ids["question_id"], "x", five).status_code == 422


def test_chatgpt_sees_photos_of_an_answer_it_reads(owner_api: Api, fake: ToolFake) -> None:  # noqa: F811
    sign_in(owner_api, fake)
    ids = owner_api.course_with_question()
    pid = photo(owner_api, ids["course_id"])
    answer(owner_api, ids["question_id"], "see photo", [pid])
    fake.rounds = [
        calls(1, ("a1", "get_answer", {"question_id": ids["question_id"]})),
        reply_events("I can read your working.", 2),
    ]
    r = send(owner_api, f"I saved my answer to question {ids['question_id']}.", course_id=ids["course_id"])
    assert r.status_code == 200, r.text
    second = fake.bodies()[1]["input"]
    shown = [i for i in second if i.get("type") == "message" and i["role"] == "user"][-1]
    assert "photo" in shown["content"][0]["text"]
    assert shown["content"][1]["type"] == "input_image"
    assert shown["content"][1]["image_url"].startswith("data:image/png;base64,")


def test_an_image_pasted_into_a_chat_message_is_sent_once_and_kept(owner_api: Api, fake: ToolFake) -> None:  # noqa: F811
    sign_in(owner_api, fake)
    ids = owner_api.course_with_question()
    pid = photo(owner_api, ids["course_id"], "task.png")
    fake.rounds = [reply_events("This is a Karnaugh map.", 1), reply_events("Yes.", 2)]
    first = send(owner_api, "What is this?", course_id=ids["course_id"], photo_ids=[pid])
    assert first.status_code == 200, first.text
    conv = first.json()
    assert conv["messages"][0]["photo_ids"] == [pid]
    content = fake.bodies()[0]["input"][-1]["content"]
    assert [c["type"] for c in content] == ["input_text", "input_image"]

    second = send(owner_api, "Sure?", conversation_id=conv["id"])
    assert second.status_code == 200, second.text
    earlier = fake.bodies()[1]["input"][0]["content"]
    assert [c["type"] for c in earlier] == ["input_text"]  # sent once; later turns only say it was there
    assert "1 image attached" in earlier[0]["text"]
