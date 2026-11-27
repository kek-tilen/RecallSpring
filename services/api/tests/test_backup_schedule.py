"""How often backups run (docs/08 -> Backups, 2026-11-27): daily to monthly or every N days, at a time of day in the
first account's time zone; a missed one runs when RecallSpring runs again; less frequent backups keep the last 7."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from recallspring_api import backup
from recallspring_api.db import new_session
from recallspring_api.main import create_app
from recallspring_api.models import AuditEvent

from .conftest import Api, make_user
from .test_backup import _fake_snapshot


@pytest.fixture
def backups(settings: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "backups"
    monkeypatch.setattr(settings, "backup_enabled", True)
    monkeypatch.setattr(settings, "backup_dir", root)
    monkeypatch.setattr(settings, "backup_settings_file", tmp_path / "backup-settings.json")
    monkeypatch.setattr(settings, "backup_settings_from_web", True)
    return root


def _good_backup_at(when: datetime) -> None:
    backup._write_json(backup._status_path(), {"last_success_at": when.isoformat()})


def test_daily_at_three_in_the_owners_time_zone(owner_api: Api, backups: Path, frozen: Any) -> None:
    view = owner_api.get("/settings/backup").json()
    assert view["schedule"] == {"every": "days", "days": 1, "day_of_month": None, "at": "03:00", "source": "server"}
    assert view["schedule_label"] == "Daily at 03:00" and view["keeps"] == "daily_weekly"
    assert view["timezone"] == "Europe/Ljubljana"
    assert view["next_due"] == "now" and backup.due()

    _good_backup_at(frozen())  # 17:00 in Ljubljana on 19 Nov
    nxt = datetime.fromisoformat(owner_api.get("/settings/backup").json()["next_due"])
    assert nxt == datetime(2026, 11, 20, 2, 0, tzinfo=UTC)  # 03:00 in Ljubljana
    frozen.set(datetime(2026, 11, 20, 1, 59, tzinfo=UTC))
    assert not backup.due()
    frozen.set(datetime(2026, 11, 20, 2, 0, tzinfo=UTC))
    assert backup.due() and backup.attention_item() is None
    # RecallSpring was off: the missed backup runs as soon as it runs again; Today says so a day after the time.
    frozen.set(datetime(2026, 11, 21, 2, 1, tzinfo=UTC))
    assert backup.due()
    item = backup.attention_item()
    assert item is not None and item["title"] == "No backup for 1 day"


def test_choosing_how_often(owner_api: Api, backups: Path, frozen: Any) -> None:
    _good_backup_at(frozen())
    r = owner_api.put("/settings/backup/schedule", {"every": "days", "days": 14, "at": "22:30"})
    assert r.status_code == 200, r.text
    view = r.json()
    assert view["schedule_label"] == "Every 2 weeks at 22:30" and view["schedule"]["source"] == "settings"
    assert view["keeps"] == "last" and view["keep_last"] == 7 and view["can_change"] is True
    assert datetime.fromisoformat(view["next_due"]) == datetime(2026, 12, 3, 21, 30, tzinfo=UTC)

    monthly = owner_api.put("/settings/backup/schedule", {"every": "monthly", "at": "03:00"}).json()
    assert monthly["schedule"]["day_of_month"] == 19  # today, in the owner's time zone
    assert monthly["schedule_label"] == "Monthly on the 19th at 03:00"
    assert datetime.fromisoformat(monthly["next_due"]) == datetime(2026, 12, 19, 2, 0, tzinfo=UTC)

    custom = owner_api.put("/settings/backup/schedule", {"every": "days", "days": 10, "at": "03:00"}).json()
    assert custom["schedule_label"] == "Every 10 days at 03:00"

    with new_session() as db:
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "backup.schedule_changed")))
    assert sorted((e.details["from"], e.details["to"]) for e in events) == sorted(
        [
            ("Daily at 03:00", "Every 2 weeks at 22:30"),
            ("Every 2 weeks at 22:30", "Monthly on the 19th at 03:00"),
            ("Monthly on the 19th at 03:00", "Every 10 days at 03:00"),
        ]
    )
    # The frozen clock gives all three the same time, so History's order among them is not defined.
    rows = [h for h in owner_api.get("/history").json() if h["type"] == "backup.schedule_changed"]
    assert {r["text"] for r in rows} == {"Backup schedule changed"}
    assert "Monthly on the 19th at 03:00 → Every 10 days at 03:00" in {r["detail"] for r in rows}


@pytest.mark.parametrize(
    "body",
    [
        {"every": "days", "days": 0, "at": "03:00"},
        {"every": "days", "days": 91, "at": "03:00"},
        {"every": "days", "at": "03:00"},
        {"every": "days", "days": 7, "at": "24:00"},
        {"every": "hourly", "days": 1, "at": "03:00"},
        {"every": "monthly", "day_of_month": 32, "at": "03:00"},
    ],
)
def test_impossible_schedules_are_refused(owner_api: Api, backups: Path, body: dict[str, Any]) -> None:
    r = owner_api.put("/settings/backup/schedule", body)
    assert r.status_code == 422, r.text
    assert owner_api.get("/settings/backup").json()["schedule"]["source"] == "server"


def test_only_the_first_account_or_the_server_sets_it(
    owner_api: Api, backups: Path, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_user("second")
    with TestClient(create_app()) as other_client:
        other = Api(other_client)
        assert other.login("second").status_code == 200
        r = other.put("/settings/backup/schedule", {"every": "days", "days": 7, "at": "03:00"})
        assert r.status_code == 403 and r.json()["code"] == "not_backup_owner"
    assert owner_api.put("/settings/backup/schedule", {"every": "days", "days": 7, "at": "03:00"}).status_code == 200
    monkeypatch.setattr(settings, "backup_settings_from_web", False)
    view = owner_api.get("/settings/backup").json()
    assert view["schedule"]["source"] == "server" and view["schedule_label"] == "Daily at 03:00"
    r = owner_api.put("/settings/backup/schedule", {"every": "days", "days": 3, "at": "03:00"})
    assert r.status_code == 403 and r.json()["code"] == "backup_folder_locked"


def test_less_frequent_backups_keep_the_last_seven(owner_api: Api, backups: Path, frozen: Any) -> None:
    assert owner_api.put("/settings/backup/schedule", {"every": "days", "days": 7, "at": "03:00"}).status_code == 200
    user = "00000000-0000-4000-8000-000000000001"
    names = [datetime(2026, 11, 19 - 7 * w, 3, 0).strftime(backup.STAMP) for w in range(3)]
    names += [datetime(2026, m, 1, 3, 0).strftime(backup.STAMP) for m in range(1, 11)]
    for i, name in enumerate(names):
        _fake_snapshot(backups, name, f"{user}/ab/{str(i).rjust(64, 'a')}")
    backup.prune()
    assert [p.name for p in backup.snapshots()] == sorted(names)[-7:]
