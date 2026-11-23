"""ChatGPT in Chat using RecallSpring (plan-without-claude.md, Phase 2) against a fake OpenAI: tools go in one
namespace, calls run on the server as the learner with the connector's checks, every step is recorded on the
learner's message, grades carry the model OpenAI reported, limits stop runaway turns, and plan-usage errors in the
middle of a turn keep what was done without any fallback. A planning conversation (no course) sets up courses and
targets but cannot quiz; a study conversation stays inside its course."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from recallspring_api.ai import siwc
from recallspring_api.config import get_settings
from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent
from recallspring_api.services import chat_tools

from .conftest import Api
from .test_chatgpt_signin import FakeOpenAI, reply_events, sign_in

MODEL = "gpt-test-2026-11-01"


class ToolFake(FakeOpenAI):
    """Answers each /v1/responses request with the next queued round: a list of events, or (status, body)."""

    def __init__(self) -> None:
        super().__init__()
        self.rounds: list[Any] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/responses" and self.rounds:
            self.requests.append(request)
            nxt = self.rounds.pop(0)
            if isinstance(nxt, tuple):
                return httpx.Response(nxt[0], json=nxt[1])
            text = "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in nxt)
            return httpx.Response(200, content=text.encode(), headers={"content-type": "text/event-stream"})
        return super().handle(request)

    def bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if r.url.path == "/v1/responses"]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> ToolFake:
    monkeypatch.setattr(get_settings(), "secrets_dir", tmp_path / "secrets")
    monkeypatch.setattr(siwc, "is_local", lambda host: True)
    f = ToolFake()
    monkeypatch.setattr(siwc, "transport", httpx.MockTransport(f.handle))
    siwc._pending.clear()
    return f


def calls(n: int, *wanted: tuple[str, str, dict[str, Any]], text: str = "") -> list[dict[str, Any]]:
    """One response asking for function calls (call_id, name, arguments)."""
    output: list[dict[str, Any]] = [
        {"type": "function_call", "id": f"fc_{n}_{i}", "call_id": cid, "name": name, "arguments": json.dumps(args)}
        for i, (cid, name, args) in enumerate(wanted)
    ]
    events: list[dict[str, Any]] = [{"type": "response.created", "response": {"id": f"resp_{n}"}}]
    if text:
        events.append({"type": "response.output_text.delta", "delta": text})
        output.insert(
            0,
            {
                "type": "message",
                "id": f"msg_{n}",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            },
        )
    events += [{"type": "response.output_item.done", "item": item} for item in output]
    events.append(
        {
            "type": "response.completed",
            "response": {
                "id": f"resp_{n}",
                "model": MODEL,
                "output": output,
                "usage": {"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
            },
        }
    )
    return events


def send(api: Api, message: str, **extra: Any) -> Any:
    return api.post("/ai/chatgpt/messages", {"model": "gpt-test", "message": message, "recallspring": True, **extra})


def outputs(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {i["call_id"]: json.loads(i["output"]) for i in body["input"] if i["type"] == "function_call_output"}


def test_tools_go_in_one_namespace_and_calls_run_as_the_learner(owner_api: Api, fake: ToolFake) -> None:
    sign_in(owner_api, fake)
    ids = owner_api.course_with_question()
    fake.rounds = [
        calls(1, ("c1", "get_course_outline", {"course_id": ids["course_id"]}), text="Let me look."),
        reply_events("Your course has one source.", 2),
    ]
    r = send(owner_api, "What is in my course?")
    assert r.status_code == 200, r.text
    first, second = fake.bodies()
    assert list(first) == list(siwc.TOOL_REQUEST_FIELDS) and first["store"] is False and first["stream"] is True
    [space] = first["tools"]
    assert space["type"] == "namespace" and space["name"] == "recallspring"
    names = {t["name"] for t in space["tools"]}
    assert len(names) <= chat_tools.MAX_TOOLS and all(t["type"] == "function" for t in space["tools"])
    assert not names & {"delete_course", "import_file", "set_availability", "create_questions", "record_assessment"}
    assert "planning conversation" in first["instructions"]
    assert "recallspring tools" in first["instructions"]
    # the call goes back without OpenAI's item id, followed by RecallSpring's output
    echoed = [i for i in second["input"] if i["type"] != "message"]
    assert echoed[0] == {
        "type": "function_call",
        "call_id": "c1",
        "name": "get_course_outline",
        "arguments": json.dumps({"course_id": ids["course_id"]}),
    }
    out = outputs(second)["c1"]
    assert out["ok"] is True and out["result"]["sources"]
    assert [i.get("role") for i in second["input"] if i["type"] == "message"] == ["user", "assistant"]

    conv = r.json()
    question, answer = conv["messages"]
    [step] = question["tool_calls"]
    assert step["name"] == "get_course_outline" and step["status"] == "ok" and step["writes"] is False
    assert step["summary"] == "Read the course outline" and step["arguments"] == {"course_id": ids["course_id"]}
    assert answer["text"] == "Let me look.\n\nYour course has one source."
    assert answer["model"] == "gpt-test-2026-11-01"
    assert answer["usage"]["input_tokens"] == 140 and answer["usage"]["total_tokens"] == 162
    with new_session() as db:
        audit = db.scalars(select(AuditEvent).where(AuditEvent.action == "ai.chatgpt_message")).one()
    assert audit.details["rounds"] == 2 and audit.details["tool_calls"][0]["name"] == "get_course_outline"
    assert "What is in my course" not in json.dumps(audit.details)


def test_grades_carry_the_model_openai_reported_and_evidence_is_checked(owner_api: Api, fake: ToolFake) -> None:
    sign_in(owner_api, fake)
    ids = owner_api.course_with_question()
    attempt = owner_api.answer(ids["question_id"], text="Glycolysis: cytoplasm, pyruvate.").json()
    grade = {
        "attempt_id": attempt["attempt_id"],
        "status": "final",
        "grade": 3,
        "confidence": "high",
        "feedback": "Right place and product.",
        "evidence_refs": [ids["section_ids"][0], str(uuid.uuid4())],
        "model_name": "a model ChatGPT names itself",
    }
    fake.rounds = [
        calls(1, ("a1", "get_answer", {"question_id": ids["question_id"]})),
        calls(2, ("g1", "record_assessments", {"items": [grade]})),
        reply_events("Solid answer. Review tomorrow.", 3),
    ]
    r = send(
        owner_api,
        f"I saved my answer to question {ids['question_id']}. Please give me feedback.",
        course_id=ids["course_id"],
    )
    assert r.status_code == 200, r.text
    read = outputs(fake.bodies()[1])["a1"]
    assert (
        read["ok"]
        and read["result"]["answered"]
        and read["result"]["answer_text"] == "Glycolysis: cytoplasm, pyruvate."
    )
    graded = outputs(fake.bodies()[2])["g1"]["result"]["results"][0]
    assert graded["schedule"], graded
    stored = owner_api.get(f"/attempts/{attempt['attempt_id']}").json()["assessments"][0]
    assert stored["provider"] == "chatgpt" and stored["model"] == MODEL and stored["model_reported_by"] == "provider"
    assert stored["evidence_refs"] == [ids["section_ids"][0]] and stored["status"] == "provisional"
    steps = r.json()["messages"][0]["tool_calls"]
    assert [s["summary"] for s in steps] == ["Read your answer", "Saved feedback: Solid (3/4) (provisional)"]
    assert steps[1]["writes"] is True
    detail = owner_api.get(f"/concepts/{ids['concept_id']}/detail").json()
    assert detail["attempts"][0]["grader"] == {"name": "ChatGPT", "model": MODEL}


def test_learning_first_forms_and_bad_calls_are_reported_back(owner_api: Api, fake: ToolFake) -> None:
    sign_in(owner_api, fake)
    ids = owner_api.course_with_question()
    new_q = {
        "course_id": ids["course_id"],
        "questions": [
            {
                "concept_ids": [ids["concept_id"]],
                "bloom_level": 1,
                "prompt": "Where does glycolysis run?",
                "expected_points": ["in the cytoplasm"],
            }
        ],
    }
    summary = {
        "course_id": ids["course_id"],
        "concept_ids": [ids["concept_id"]],
        "title": "Glycolysis",
        "covered": "pages 1-2",
    }
    fake.rounds = [
        calls(
            1,
            ("q1", "create_questions", new_q),
            ("f1", "open_answer_form", {"question_id": ids["question_id"]}),
            ("s1", "recallspring.open_summary_form", summary),
            ("x1", "delete_course", {"course_id": ids["course_id"]}),
            ("x2", "get_source_section", {"section_id": "page-99"}),
            ("x3", "open_answer_form", {"question_id": str(uuid.uuid4())}),
        ),
        reply_events("Answer below.", 2),
    ]
    r = send(owner_api, "Quiz me", course_id=ids["course_id"])
    assert r.status_code == 200, r.text
    out = outputs(fake.bodies()[1])
    assert out["q1"]["error"] == "concepts_not_studied"
    assert out["f1"]["ok"] and out["s1"]["ok"]
    assert out["x1"]["error"] == "unknown_tool" and out["x2"]["error"] == "invalid_arguments"
    assert out["x3"]["error"] == "not_found"
    steps = {s["call_id"]: s for s in r.json()["messages"][0]["tool_calls"]}
    assert steps["q1"]["status"] == "error" and steps["q1"]["error_code"] == "concepts_not_studied"
    assert steps["f1"]["form"] == {"kind": "answer", "question_id": ids["question_id"]}
    assert steps["s1"]["name"] == "open_summary_form" and steps["s1"]["form"]["kind"] == "summary"
    assert steps["s1"]["form"]["concept_ids"] == [ids["concept_id"]]
    assert "form" not in steps["x3"]
    with new_session() as db:
        from recallspring_api.models import Question

        assert len(list(db.scalars(select(Question)))) == 1  # the refused question was not saved


def test_limits_stop_a_runaway_turn(owner_api: Api, fake: ToolFake) -> None:
    sign_in(owner_api, fake)
    many = [(f"c{i}", "list_courses", {}) for i in range(chat_tools.MAX_CALLS + 1)]
    fake.rounds = [calls(1, *many), reply_events("Done.", 2)]
    r = send(owner_api, "Hi")
    steps = r.json()["messages"][0]["tool_calls"]
    assert len(steps) == chat_tools.MAX_CALLS + 1
    assert steps[-1]["error_code"] == "too_many_calls" and outputs(fake.bodies()[1])[many[-1][0]]["ok"] is False

    fake.requests.clear()
    fake.rounds = [calls(n, (f"r{n}", "list_courses", {})) for n in range(1, chat_tools.MAX_ROUNDS + 2)]
    r = send(owner_api, "Again", conversation_id=r.json()["id"])
    assert r.status_code == 200, r.text
    assert len(fake.bodies()) == chat_tools.MAX_ROUNDS
    assert "RecallSpring stopped here" in r.json()["messages"][-1]["text"]


def test_a_usage_limit_mid_turn_keeps_the_steps_without_any_fallback(owner_api: Api, fake: ToolFake) -> None:
    sign_in(owner_api, fake)
    fake.rounds = [
        calls(1, ("c1", "list_courses", {})),
        (429, {"error": {"code": "subscription_sharing_usage_limit_exceeded"}}),
    ]
    r = send(owner_api, "Plan my week")
    assert r.status_code == 429 and r.json()["code"] == "chatgpt_usage_limit"
    conv = owner_api.get(f"/ai/chatgpt/conversations/{r.json()['details']['conversation_id']}").json()
    [question] = conv["messages"]
    assert question["error_code"] == "usage_limit" and question["tool_calls"][0]["status"] == "ok"
    hosts = {r.url.host for r in fake.requests}
    assert hosts <= {"auth.openai.com", "api.openai.com"}


def test_unsupported_tools_are_named_and_never_dropped_silently(owner_api: Api, fake: ToolFake) -> None:
    sign_in(owner_api, fake)
    fake.rounds = [
        (400, {"error": {"code": "subscription_sharing_unsupported_capability", "param": "tools", "message": "x"}})
    ]
    r = send(owner_api, "Hi")
    assert r.status_code == 422 and r.json()["code"] == "chatgpt_unsupported"
    assert "tools" in r.json()["message"] and "Use RecallSpring" in r.json()["message"]
    assert r.json()["details"]["param"] == "tools"
    assert len(fake.bodies()) == 1  # not resent without the tools


def test_study_mode_names_the_course_and_only_the_learners_own(owner_api: Api, fake: ToolFake, client: Any) -> None:
    sign_in(owner_api, fake)
    ids = owner_api.course_with_question()
    fake.rounds = [reply_events("Let's start.", 1)]
    r = send(owner_api, "Start studying", course_id=ids["course_id"])
    assert r.status_code == 200, r.text
    assert r.json()["course"] == {"id": ids["course_id"], "title": "Biology 101"}
    instructions = fake.bodies()[0]["instructions"]
    assert ids["course_id"] in instructions and "Biology 101" in instructions

    r = send(owner_api, "Other", course_id=str(uuid.uuid4()))
    assert r.status_code == 404

    fake.rounds = [reply_events("Plain.", 2)]
    plain = owner_api.post("/ai/chatgpt/messages", {"model": "gpt-test", "message": "No tools"})
    assert plain.status_code == 200 and "tools" not in fake.bodies()[-1]
    assert plain.json()["course"] is None and plain.json()["messages"][0]["tool_calls"] == []


def _targets() -> list[Any]:
    from recallspring_api.models import StudyTarget

    with new_session() as db:
        return list(db.scalars(select(StudyTarget).order_by(StudyTarget.created_at)))


def test_a_planning_conversation_sets_up_the_semester_but_cannot_quiz(owner_api: Api, fake: ToolFake) -> None:
    sign_in(owner_api, fake)
    ids = owner_api.course_with_question()
    target = {
        "course_id": ids["course_id"],
        "kind": "kolokvij",
        "name": "1. kolokvij",
        "due_date": "2026-12-15",
        "scope_description": "Prvi del, do glikolize",
        "scope": [{"kind": "concept", "concept_id": ids["concept_id"]}],
    }
    concepts = {
        "course_id": ids["course_id"],
        "concepts": [{"term": "Krebs cycle", "source_section_ids": ids["section_ids"][:1]}],
    }
    quiz = {"course_id": ids["course_id"], "questions": [{"concept_ids": [ids["concept_id"]], "prompt": "Why?"}]}
    fake.rounds = [
        calls(
            1,
            ("p1", "create_course", {"title": "Genetics"}),
            ("p2", "create_course", {"title": "Biology 101"}),
            ("p3", "create_concepts", concepts),
            ("p4", "set_study_target", target),
            ("p5", "create_questions", quiz),
        ),
        reply_events("Your semester is set up.", 2),
    ]
    r = send(owner_api, "Let's set up my semester.")
    assert r.status_code == 200, r.text
    [space] = fake.bodies()[0]["tools"]
    names = {t["name"] for t in space["tools"]}
    assert {"create_course", "organise_courses", "set_study_target", "record_exam_profile"} <= names
    assert len(names) <= chat_tools.MAX_TOOLS and "open_answer_form" not in names
    out = outputs(fake.bodies()[1])
    assert out["p1"]["ok"] and out["p1"]["result"]["title"] == "Genetics"
    assert out["p2"]["ok"] is False  # the course exists already
    assert out["p3"]["ok"] and out["p3"]["result"]["concepts"][0]["source_section_ids"] == ids["section_ids"][:1]
    assert out["p4"]["ok"] and out["p4"]["result"]["scope_description"] == "Prvi del, do glikolize"
    assert out["p5"]["error"] == "not_in_this_conversation" and "Study" in out["p5"]["message"]
    steps = {s["call_id"]: s for s in r.json()["messages"][0]["tool_calls"]}
    assert steps["p1"]["summary"] == "Created the course Genetics" and steps["p1"]["writes"] is True
    assert steps["p4"]["summary"] == "Saved 1. kolokvij on 2026-12-15"
    genetics = next(c for c in owner_api.get("/courses").json() if c["title"] == "Genetics")

    [saved] = _targets()
    profile = {
        "target_id": str(saved.id),
        "item_types": [{"type": "short answer", "share": 1}],
        "example_items": ["Explain glycolysis."],
        "model_name": "a model ChatGPT names itself",
    }
    fake.rounds = [
        calls(
            3,
            ("u1", "update_study_target", {"target_id": str(saved.id), "due_date": "2026-12-18"}),
            ("u2", "record_exam_profile", profile),
            ("u3", "organise_courses", {"course_ids": [genetics["id"]], "semester": "5. semester", "faculty": "FKKT"}),
        ),
        reply_events("Moved and analysed.", 4),
    ]
    r = send(owner_api, "The kolokvij moved to 18 December; here is last year's paper.", conversation_id=r.json()["id"])
    assert r.status_code == 200, r.text
    out = outputs(fake.bodies()[-1])
    assert out["u1"]["ok"] and out["u1"]["result"]["due_date"] == "2026-12-18"
    assert out["u2"]["ok"] and out["u3"]["ok"], (out["u2"], out["u3"])
    from recallspring_api.models import TargetProfile

    with new_session() as db:
        stored = db.scalars(select(TargetProfile)).one()
    assert stored.model == MODEL  # what OpenAI reported, not what ChatGPT wrote
    assert [s["summary"] for s in r.json()["messages"][-2]["tool_calls"]] == [
        "Updated the study target",
        "Saved the exam profile",
        "Filed 1 course under 5. semester",
    ]


def test_a_study_conversation_sets_up_only_its_own_course(owner_api: Api, fake: ToolFake) -> None:
    sign_in(owner_api, fake)
    ids = owner_api.course_with_question()
    other = owner_api.post("/courses", {"title": "Chemistry"}).json()
    base = {"kind": "izpit", "name": "Exam", "due_date": "2027-01-20", "scope_description": "Everything"}
    fake.rounds = [
        calls(
            1,
            ("s1", "set_study_target", {**base, "course_id": ids["course_id"]}),
            ("s2", "set_study_target", {**base, "course_id": other["id"]}),
            ("s3", "list_courses", {}),
            ("s4", "create_course", {"title": "Physics"}),
        ),
        reply_events("Saved your exam.", 2),
    ]
    r = send(owner_api, "My exam is on 20 January, everything.", course_id=ids["course_id"])
    assert r.status_code == 200, r.text
    [space] = fake.bodies()[0]["tools"]
    names = {t["name"] for t in space["tools"]}
    assert len(names) <= chat_tools.MAX_TOOLS
    assert {"create_questions", "open_answer_form", "set_study_target", "create_concepts"} <= names
    assert not names & {"create_course", "organise_courses", "list_courses"}
    assert "needs_setup" in fake.bodies()[0]["instructions"] and "set_study_target" in fake.bodies()[0]["instructions"]
    out = outputs(fake.bodies()[1])
    assert out["s1"]["ok"]
    assert out["s2"]["error"] == "other_course"
    assert out["s3"]["error"] == out["s4"]["error"] == "not_in_this_conversation"
    assert [t.course_id for t in _targets()] == [uuid.UUID(ids["course_id"])]

    [saved] = _targets()
    elsewhere = owner_api.post("/targets", {**base, "course_id": other["id"], "name": "Chem exam"})
    assert elsewhere.status_code == 201, elsewhere.text
    fake.rounds = [
        calls(3, ("m1", "update_study_target", {"target_id": elsewhere.json()["id"], "status": "passed"})),
        reply_events("Only this course.", 4),
    ]
    r = send(owner_api, "I passed chemistry.", conversation_id=r.json()["id"])
    # results and dates are saved in a planning conversation (Chat without a course)
    assert outputs(fake.bodies()[-1])["m1"]["error"] == "not_in_this_conversation"
    assert next(t for t in _targets() if t.id == saved.id).status == "upcoming"


def test_concept_to_clarity_in_a_study_conversation(owner_api: Api, fake: ToolFake) -> None:
    """C2C (ADR-010): ChatGPT shows the explanation form, reads the learner's saved version and gives feedback on it
    (not a grade), recorded with the model OpenAI reported."""
    sign_in(owner_api, fake)
    ids = owner_api.course_with_question()
    cid = ids["concept_id"]
    fake.rounds = [
        calls(1, ("e1", "open_explanation_form", {"concept_id": cid, "source": "discuss"})),
        reply_events("Explain it below.", 2),
    ]
    r = send(owner_api, "Let me explain glycolysis", course_id=ids["course_id"])
    assert r.status_code == 200, r.text
    names = json.dumps(fake.bodies()[0]["tools"])
    for tool in ("get_explanation", "open_explanation_form", "record_explanation_feedback"):
        assert tool in names
    step = r.json()["messages"][0]["tool_calls"][0]
    assert step["form"] == {"kind": "explanation", "concept_id": cid, "term": "Glycolysis", "source": "discuss"}

    key = str(uuid.uuid4())
    body = {"text": "Glycolysis runs in the mitochondria.", "source": "discuss", "client_request_id": key}
    saved = owner_api.post(f"/concepts/{cid}/explanation/versions", body, key=key).json()
    vid = saved["versions"][0]["id"]
    feedback = {
        "version_id": vid,
        "correct": ["Names glycolysis"],
        "wrong": ["It runs in the cytoplasm"],
        "evidence_refs": [ids["section_ids"][0]],
        "feedback": "Check where it happens.",
    }
    fake.rounds = [
        calls(3, ("g1", "get_explanation", {"concept_id": cid}), ("r1", "record_explanation_feedback", feedback)),
        reply_events("Here is my feedback.", 4),
    ]
    conv = r.json()["id"]
    r = send(owner_api, "Saved version 1", conversation_id=conv, course_id=ids["course_id"])
    assert r.status_code == 200, r.text
    out = outputs(fake.bodies()[-1])
    assert out["g1"]["result"]["versions"][0]["text"] == "Glycolysis runs in the mitochondria."
    assert out["r1"]["ok"] and out["r1"]["result"]["dropped_refs"] == 0
    [fb] = owner_api.get(f"/concepts/{cid}/explanation").json()["versions"][0]["feedback"]
    assert fb["grader"]["model"] == MODEL and fb["wrong"] == ["It runs in the cytoplasm"]
    assert "grade" not in fb
