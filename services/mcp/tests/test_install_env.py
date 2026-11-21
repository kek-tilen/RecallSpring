"""scripts/install_env.py: the settings files a new install needs, made once and never overwritten."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "install_env.py"
_spec = importlib.util.spec_from_file_location("install_env", SCRIPT)
assert _spec and _spec.loader
env: Any = importlib.util.module_from_spec(_spec)
sys.modules["install_env"] = env
_spec.loader.exec_module(env)


def test_a_new_install_gets_a_random_password_used_in_both_files(tmp_path: Path) -> None:
    assert env.ensure_env(tmp_path) == ["infra/.env", "services/api/.env"]
    password = env._password(tmp_path / "infra" / ".env")
    assert password and len(password) >= 30
    api = (tmp_path / "services" / "api" / ".env").read_text(encoding="utf-8")
    assert f"recallspring:{password}@127.0.0.1:55432/recallspring" in api
    assert "RS_COOKIE_SECURE=false" in api and "mock" not in api
    other = tmp_path / "other"
    env.ensure_env(other)
    assert env._password(other / "infra" / ".env") != password


def test_existing_settings_are_never_changed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / ".env").write_text("RS_DEV_DB_PASSWORD=mine\n", encoding="utf-8")
    (tmp_path / "services" / "api").mkdir(parents=True)
    (tmp_path / "services" / "api" / ".env").write_text("RS_DATABASE_URL=custom\n", encoding="utf-8")
    assert env.main(["env", "--root", str(tmp_path)]) == 0
    assert "left unchanged" in capsys.readouterr().out
    assert (tmp_path / "infra" / ".env").read_text(encoding="utf-8") == "RS_DEV_DB_PASSWORD=mine\n"
    assert (tmp_path / "services" / "api" / ".env").read_text(encoding="utf-8") == "RS_DATABASE_URL=custom\n"


def test_only_the_api_file_is_added_next_to_an_existing_password(tmp_path: Path) -> None:
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / ".env").write_text("# mine\nRS_DEV_DB_PASSWORD = s3cret\n", encoding="utf-8")
    assert env.ensure_env(tmp_path) == ["services/api/.env"]
    assert "recallspring:s3cret@" in (tmp_path / "services" / "api" / ".env").read_text(encoding="utf-8")


def test_a_password_file_without_a_password_stops_the_install(tmp_path: Path) -> None:
    (tmp_path / "infra").mkdir()
    (tmp_path / "infra" / ".env").write_text("# empty\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="RS_DEV_DB_PASSWORD"):
        env.ensure_env(tmp_path)
    assert not (tmp_path / "services" / "api" / ".env").exists()


def test_the_password_is_never_printed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env.main(["env", "--root", str(tmp_path)])
    out = capsys.readouterr().out
    assert env._password(tmp_path / "infra" / ".env") not in out
    assert env.main(["check-python"]) == 0
