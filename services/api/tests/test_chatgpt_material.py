"""ChatGPT conversations may use files the learner chooses: only matching excerpts of those files are sent, what
was sent is recorded with the message, and replies may cite and ground visuals only on what was really sent."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent
from recallspring_api.services import chat_material

from .conftest import Api, run_pending
from .test_chatgpt_signin import FakeOpenAI, install_fake_openai, reply_events, sign_in


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> FakeOpenAI:
    return install_fake_openai(monkeypatch, tmp_path)


QA = """# Zagotavljanje kakovosti

Zagotavljanje kakovosti je sistem postopkov, ki preprečuje napake v procesu razvoja.

# Testiranje obremenitve

Spike testiranje preverja odziv sistema na nenaden velik porast obremenitve.
"""
OTHER = "# Recepti\n\nPalačinke potrebujejo moko, mleko in jajca.\n"


def put(api: Api, path: str, body: Any) -> Any:
    return api.client.put(f"/api/v1{path}", json=body, headers=api.headers())


def material(api: Api) -> tuple[str, str]:
    course = api.post("/courses", {"title": "Kakovost"}).json()
    qa = api.paste(course["id"], QA, title="Kakovost").json()
    other = api.paste(course["id"], OTHER, title="Recepti").json()
    run_pending()
    return qa["id"], other["id"]


def sent_instructions(fake: FakeOpenAI) -> str:
    return json.loads(fake.requests[-1].content)["instructions"]


def test_only_chosen_files_are_sent_and_the_excerpts_are_recorded(owner_api: Api, fake: FakeOpenAI) -> None:
    sign_in(owner_api, fake)
    qa, other = material(owner_api)

    fake.events = reply_events("Brez gradiva.")
    plain = owner_api.post("/ai/chatgpt/messages", {"model": "gpt-test", "message": "Kaj je spike?"}).json()
    assert "Excerpts:" not in sent_instructions(fake) and plain["material"] == []
    assert plain["messages"][0]["context"] == []

    fake.events = reply_events("Spike je nenaden porast [S2]. Glej tudi [S9].", 2)
    conv = owner_api.post(
        "/ai/chatgpt/messages", {"model": "gpt-test", "message": "Kaj je spike testiranje?", "source_ids": [qa]}
    ).json()
    sent = sent_instructions(fake)
    assert "Spike testiranje preverja" in sent and "Palačinke" not in sent  # small file: sent whole, other not chosen
    assert [m["filename"] for m in conv["material"]] == ["Kakovost.md"]
    question, reply = conv["messages"]
    assert [c["ref"] for c in question["context"]] == ["S1", "S2"]
    assert set(reply["citations"]) == {"S2"}  # S9 was never sent, so it is not a citation
    assert reply["citations"]["S2"]["source_id"] == qa

    with new_session() as db:
        audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "ai.chatgpt_material_chosen"))
        assert audit is not None and audit.details == {"files": 1, "added": 1, "removed": 0}

    # Choosing another file later: refs already used keep their numbers, new sections get new ones.
    r = put(owner_api, f"/ai/chatgpt/conversations/{conv['id']}/material", {"source_ids": [qa, other]})
    assert r.status_code == 200, r.text
    fake.events = reply_events("Moka [S3].", 3)
    conv = owner_api.post(
        "/ai/chatgpt/messages", {"conversation_id": conv["id"], "model": "gpt-test", "message": "In palačinke?"}
    ).json()
    refs = {c["ref"]: c["filename"] for c in conv["messages"][2]["context"]}
    assert refs["S1"] == refs["S2"] == "Kakovost.md" and refs["S3"] == "Recepti.md"

    # No files: nothing is sent any more.
    put(owner_api, f"/ai/chatgpt/conversations/{conv['id']}/material", {"source_ids": []})
    fake.events = reply_events("OK.", 4)
    owner_api.post("/ai/chatgpt/messages", {"conversation_id": conv["id"], "model": "gpt-test", "message": "Hvala"})
    assert "Excerpts:" not in sent_instructions(fake)


def test_visuals_keep_only_references_that_were_sent(owner_api: Api, fake: FakeOpenAI) -> None:
    sign_in(owner_api, fake)
    qa, _ = material(owner_api)
    chart = {
        "type": "data_chart",
        "title": "Obremenitev",
        "alt_text": "Load jumps.",
        "source_refs": ["S2", "S7", "sec_fake"],
        "illustrative": False,
        "data": {"chart": "bar", "x_label": "t", "y_label": "n", "points": [{"x": "a", "y": 1}, {"x": "b", "y": 9}]},
    }
    fake.events = reply_events(f"Graf:\n\n```recallspring-visual\n{json.dumps(chart)}\n```")
    conv = owner_api.post(
        "/ai/chatgpt/messages", {"model": "gpt-test", "message": "Pokaži spike", "source_ids": [qa]}
    ).json()
    [visual] = conv["messages"][1]["visuals"]
    assert visual["block"]["source_refs"] == ["S2"] and visual["block"]["illustrative"] is False
    assert set(conv["messages"][1]["citations"]) == {"S2"}


def test_large_files_send_matching_parts_within_the_budget(owner_api: Api, fake: FakeOpenAI, monkeypatch: Any) -> None:
    sign_in(owner_api, fake)
    course = owner_api.post("/courses", {"title": "Velik"}).json()
    chapters = "\n\n".join(f"# Poglavje {i}\n\n" + ("polnilo " * 120) for i in range(30))
    chapters += "\n\n# Spike\n\nSpike testiranje meri nenadne skoke obremenitve.\n"
    big = owner_api.paste(course["id"], chapters, title="Velik").json()
    run_pending()
    monkeypatch.setattr(chat_material, "BUDGET", 2_000)
    fake.events = reply_events("OK.")
    conv = owner_api.post(
        "/ai/chatgpt/messages",
        {"model": "gpt-test", "message": "Kaj meri spike testiranje?", "source_ids": [big["id"]]},
    ).json()
    sent = sent_instructions(fake)
    assert "Spike testiranje meri" in sent and "best match" in sent
    assert sum(c["chars"] for c in conv["messages"][0]["context"]) <= 2_000


def test_files_must_be_the_learners_own(owner_api: Api, fake: FakeOpenAI) -> None:
    sign_in(owner_api, fake)
    qa, _ = material(owner_api)
    fake.events = reply_events("OK.")
    conv = owner_api.post("/ai/chatgpt/messages", {"model": "gpt-test", "message": "Živjo"}).json()
    r = put(owner_api, f"/ai/chatgpt/conversations/{conv['id']}/material", {"source_ids": [str(uuid.uuid4())]})
    assert r.status_code == 404
    r = put(owner_api, f"/ai/chatgpt/conversations/{conv['id']}/material", {"source_ids": [qa] * 21})
    assert r.status_code == 422
    assert (
        owner_api.client.put(
            f"/api/v1/ai/chatgpt/conversations/{conv['id']}/material", json={"source_ids": [qa]}
        ).status_code
        == 403
    )  # no CSRF token


def test_query_terms_are_plain_prefixes() -> None:
    assert chat_material._terms("Kaj je spike testiranje? ') | !x") == "kaj:* | spike:* | testir:*"
    assert chat_material._terms("a b") is None
