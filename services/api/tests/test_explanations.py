"""Concept-to-Clarity (ADR-010): the learner's explanation of a concept is kept in versions, exactly as written;
assistants give feedback per version with real cited sections and never a grade; an exam answer can become a
version only when the learner adds it; versions are deleted softly and can be restored."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent

from .conftest import Api, ConnectorApi


def write(api: Api | ConnectorApi, concept_id: str, text: str, **extra: Any) -> Any:
    body = {"text": text, "client_request_id": str(uuid.uuid4()), **extra}
    return api.post(f"/concepts/{concept_id}/explanation/versions", body, key=body["client_request_id"])


def test_versions_are_kept_exactly_and_numbered(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    cid = ids["concept_id"]
    assert owner_api.get(f"/concepts/{cid}/explanation").json()["versions"] == []
    first = write(owner_api, cid, "  Glycolysis splits glucose.\n")
    assert first.status_code == 201, first.text
    key = str(uuid.uuid4())
    body = {"text": "Glycolysis splits glucose into two pyruvate in the cytoplasm.", "client_request_id": key}
    owner_api.post(f"/concepts/{cid}/explanation/versions", body, key=key)
    again = owner_api.post(f"/concepts/{cid}/explanation/versions", body, key=key)  # a retry saves nothing new
    view = again.json()
    assert [(v["number"], v["text"], v["source"]) for v in view["versions"]] == [
        (1, "  Glycolysis splits glucose.\n", "learner"),
        (2, "Glycolysis splits glucose into two pyruvate in the cytoplasm.", "learner"),
    ]
    assert view["versions"][1]["words"] == 9 and view["concept"]["term"] == "Glycolysis"
    assert write(owner_api, cid, "   ").json()["code"] == "empty_explanation"
    # saving an explanation is the learner's evidence, not the scheduler's: the concept stays as it was
    detail = owner_api.get(f"/concepts/{cid}/detail").json()
    assert detail["study_status"] == "not_studied"
    with new_session() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "explanation.version_saved")))
    assert [e.details["version"] for e in events] == [1, 2]
    assert all("glucose" not in str(e.details) for e in events)  # no learner text in the audit log


def test_feedback_cites_only_real_sections_and_is_never_a_grade(owner_api: Api, conn: ConnectorApi) -> None:
    ids = owner_api.course_with_question()
    cid = ids["concept_id"]
    version = write(conn, cid, "Glycolysis happens in the mitochondria.").json()["versions"][0]
    shown = conn.get(f"/concepts/{cid}/explanation").json()
    assert "never rewrite" in shown["how"] and shown["versions"][0]["text"] == version["text"]
    fake = str(uuid.uuid4())
    r = conn.post(
        f"/explanation-versions/{version['id']}/feedback",
        {
            "correct": ["Names glycolysis as splitting glucose"],
            "missing": ["The two pyruvate molecules"],
            "wrong": ["It runs in the cytoplasm, not the mitochondria"],
            "evidence_refs": [ids["section_ids"][0], fake],
            "feedback": "Close, but check where it happens.",
            "model_name": "claude-test",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["dropped_refs"] == 1 and not {"grade", "status"} & set(out["explanation"]["versions"][0]["feedback"][0])
    fb = out["explanation"]["versions"][0]["feedback"][0]
    assert fb["evidence_refs"] == [ids["section_ids"][0]]
    assert fb["wrong"] == ["It runs in the cytoplasm, not the mitochondria"]
    assert fb["grader"] == {"name": "Claude", "model": "claude-test"}
    too_long = conn.post(f"/explanation-versions/{version['id']}/feedback", {"feedback": "x", "missing": ["y" * 501]})
    assert too_long.status_code == 422


def test_an_exam_answer_becomes_a_version_only_when_the_learner_adds_it(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    cid = ids["concept_id"]
    attempt = owner_api.answer(ids["question_id"], "Glycolysis: cytoplasm, two pyruvate.").json()
    assert owner_api.get(f"/concepts/{cid}/explanation").json()["versions"] == []  # never automatic
    r = write(owner_api, cid, "ignored", from_attempt_id=attempt["attempt_id"])
    assert r.status_code == 201, r.text
    [v] = r.json()["versions"]
    assert (v["text"], v["source"], v["source_attempt_id"]) == (
        "Glycolysis: cytoplasm, two pyruvate.",
        "exam_answer",
        attempt["attempt_id"],
    )
    other = owner_api.post(f"/courses/{ids['course_id']}/concepts", {"term": "Krebs cycle"}).json()
    wrong = write(owner_api, other["id"], "x", from_attempt_id=attempt["attempt_id"])
    assert wrong.status_code == 422 and wrong.json()["code"] == "attempt_not_for_concept"


def test_versions_are_deleted_softly_and_restored(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    cid = ids["concept_id"]
    v = write(owner_api, cid, "First try.").json()["versions"][0]
    headers = owner_api.headers()
    gone = owner_api.client.delete(f"/api/v1/explanation-versions/{v['id']}", headers=headers).json()
    assert gone["versions"] == [] and [d["number"] for d in gone["deleted"]] == [1]
    assert write(owner_api, cid, "Second try.").json()["versions"][0]["number"] == 2  # numbers are never reused
    back = owner_api.post(f"/explanation-versions/{v['id']}/restore").json()
    assert [x["number"] for x in back["versions"]] == [1, 2] and back["deleted"] == []
    no_csrf = owner_api.client.delete(f"/api/v1/explanation-versions/{v['id']}")
    assert no_csrf.status_code == 403


def test_explanations_stay_private_to_their_owner(owner_api: Api) -> None:
    ids = owner_api.course_with_question()
    v = write(owner_api, ids["concept_id"], "Mine.").json()["versions"][0]
    from .conftest import make_user

    make_user("other")
    owner_api.client.cookies.clear()
    assert owner_api.login("other").status_code == 200
    assert owner_api.get(f"/concepts/{ids['concept_id']}/explanation").status_code == 404
    assert owner_api.post(f"/explanation-versions/{v['id']}/restore").status_code == 404
