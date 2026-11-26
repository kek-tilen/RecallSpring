"""Explanation pace (2026-11-26; migration 0035): a default in Settings, a course may choose its
own, and an assistant saves a pace only when the learner says yes (through the connector). Every change is audited."""

from __future__ import annotations

from sqlalchemy import select

from recallspring_api.db import new_session
from recallspring_api.models import AuditEvent

from .conftest import Api, ConnectorApi
from .test_learning_first import course


def pace_in_context(conn: ConnectorApi, cid: str) -> tuple[str, str]:
    view = conn.get(f"/courses/{cid}/context").json()["explanation_pace"]
    assert view["how"] and "completely and concretely" in view["how_to_use"]
    return view["pace"], view["source"]


def test_default_in_settings_and_a_course_of_its_own(owner_api: Api, conn: ConnectorApi) -> None:
    cid, _ = course(conn, ["Topic"])
    assert owner_api.get("/auth/session").json()["user"]["explanation_pace"] == "auto"
    assert pace_in_context(conn, cid) == ("auto", "default")

    user = owner_api.put("/settings/profile", {"explanation_pace": "step"}).json()
    assert user["explanation_pace"] == "step"
    assert pace_in_context(conn, cid) == ("step", "default")

    own = owner_api.put(f"/courses/{cid}/explanation-pace", {"pace": "chunks"}).json()
    assert (own["pace"], own["label"], own["source"], own["default"]) == ("chunks", "Larger chunks", "course", "step")
    assert pace_in_context(conn, cid) == ("chunks", "course")
    listed = {c["id"]: c for c in owner_api.get("/courses").json()}
    assert listed[cid]["explanation_pace"] == "chunks"

    assert owner_api.put(f"/courses/{cid}/explanation-pace", {"pace": "fast"}).status_code == 422
    assert owner_api.put("/settings/profile", {"explanation_pace": "fast"}).status_code == 422
    back = owner_api.put(f"/courses/{cid}/explanation-pace", {"pace": None}).json()
    assert (back["pace"], back["source"]) == ("step", "default")


def test_an_assistant_saves_it_only_as_asked(owner_api: Api, conn: ConnectorApi) -> None:
    cid, _ = course(conn, ["Topic"])
    saved = conn.post("/explanation-pace", {"pace": "balanced"}).json()
    assert (saved["pace"], saved["source"]) == ("balanced", "default")
    assert owner_api.get("/auth/session").json()["user"]["explanation_pace"] == "balanced"

    mine = conn.post("/explanation-pace", {"pace": "step", "course_id": cid}).json()
    assert (mine["pace"], mine["source"]) == ("step", "course")
    assert pace_in_context(conn, cid) == ("step", "course")
    assert conn.post("/explanation-pace", {"course_id": cid}).json()["source"] == "default"  # follow the default
    assert conn.post("/explanation-pace", {}).status_code == 422  # a default needs a pace

    with new_session() as db:
        wanted = ["settings.explanation_pace", "course.explanation_pace"]
        actions = db.scalars(select(AuditEvent.action).where(AuditEvent.action.in_(wanted))).all()
    assert sorted(actions) == ["course.explanation_pace", "course.explanation_pace", "settings.explanation_pace"]
