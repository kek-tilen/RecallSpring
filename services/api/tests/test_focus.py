"""Pomodoro focus time: saving finished blocks (safe to retry), validation, the summary by day and course, History
and what Claude sees in the study context."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from .conftest import Api, ConnectorApi, FrozenClock

NOW = datetime(2026, 11, 19, 16, 0, tzinfo=UTC)  # the frozen clock: 17:00 in Europe/Ljubljana


def block(minutes: int = 45, *, ended: datetime = NOW, focused: int | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "client_session_id": str(uuid.uuid4()),
        "started_at": (ended - timedelta(minutes=minutes)).isoformat(),
        "ended_at": ended.isoformat(),
        "planned_minutes": minutes,
        "focused_seconds": minutes * 60 if focused is None else focused,
        "completed": True,
        **extra,
    }


def course(api: Api, title: str = "Statistika") -> str:
    r = api.post("/courses", {"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_a_finished_block_is_saved_once_and_summed(owner_api: Api, frozen: FrozenClock) -> None:
    stats = course(owner_api)
    b = block(course_id=stats)
    r = owner_api.post("/focus-sessions", b)
    assert r.status_code == 201, r.text
    saved = r.json()
    assert saved["course_title"] == "Statistika" and saved["minutes"] == 45 and saved["completed"] is True

    # A retry after a lost response (new request key, same block) does not count twice.
    again = owner_api.post("/focus-sessions", b)
    assert again.status_code == 200 and again.json()["id"] == saved["id"]
    assert again.headers["Idempotent-Replay"] == "true"

    stopped = block(30, ended=NOW - timedelta(hours=1), focused=12 * 60, completed=False)
    assert owner_api.post("/focus-sessions", stopped).status_code == 201
    yesterday = block(ended=NOW - timedelta(days=1))
    assert owner_api.post("/focus-sessions", {**yesterday, "course_id": stats}).status_code == 201

    s = owner_api.get("/focus/summary").json()
    assert s["today"] == {"date": "2026-11-19", "minutes": 57, "sessions": 2}
    assert [d["date"] for d in s["days"]][-2:] == ["2026-11-18", "2026-11-19"] and len(s["days"]) == 7
    assert s["days"][-2]["minutes"] == 45 and s["week_minutes"] == 102
    assert s["by_course"] == [
        {"course_id": stats, "course_title": "Statistika", "minutes": 90, "sessions": 2},
        {"course_id": None, "course_title": None, "minutes": 12, "sessions": 1},
    ]
    assert [r["minutes"] for r in s["recent"]] == [45, 12, 45]

    rows = [h for h in owner_api.get("/history").json() if h["type"].startswith("focus.")]
    assert {(h["text"], h["detail"], h["label"]) for h in rows} == {
        ("Focus block finished", "45 of 45 min", "Statistika"),
        ("Focus block stopped early", "12 of 30 min", "No course"),
    }


def test_impossible_blocks_are_refused(owner_api: Api, frozen: FrozenClock) -> None:
    cases = [
        (block(focused=50 * 60), "focus_longer_than_block"),
        (block(ended=NOW + timedelta(minutes=10)), "focus_time_out_of_range"),
        (block(ended=NOW - timedelta(days=8)), "focus_time_out_of_range"),
        ({**block(), "started_at": (NOW + timedelta(minutes=1)).isoformat()}, "ended_before_start"),
    ]
    for payload, code in cases:
        r = owner_api.post("/focus-sessions", payload)
        assert r.status_code == 422 and r.json()["code"] == code, (code, r.text)
    # Under a minute is not kept; more than four hours is not a Pomodoro.
    assert owner_api.post("/focus-sessions", block(focused=30)).status_code == 422
    assert owner_api.post("/focus-sessions", block(planned_minutes=500)).status_code == 422
    assert owner_api.get("/focus/summary").json()["recent"] == []


def test_only_your_own_course(owner_api: Api, frozen: FrozenClock) -> None:
    r = owner_api.post("/focus-sessions", block(course_id=str(uuid.uuid4())))
    assert r.status_code == 404


def test_claude_sees_focus_time_as_effort_only(owner_api: Api, conn: ConnectorApi, frozen: FrozenClock) -> None:
    stats = course(owner_api)
    other = course(owner_api, "Fizika")
    assert owner_api.post("/focus-sessions", block(course_id=stats)).status_code == 201
    assert owner_api.post("/focus-sessions", block(25, course_id=other)).status_code == 201
    old = block(ended=NOW - timedelta(days=3), course_id=stats)
    assert owner_api.post("/focus-sessions", old).status_code == 201

    focus = conn.get(f"/courses/{stats}/context").json()["focus_time"]
    assert focus["today_minutes"] == 45 and focus["last_7_days_minutes"] == 90 and focus["sessions_last_7_days"] == 2
    assert "never what they learned" in focus["how_to_use"]
