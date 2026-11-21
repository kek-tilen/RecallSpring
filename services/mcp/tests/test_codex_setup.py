"""scripts/codex_setup.py: RecallSpring's block in Codex's config.toml and the study folders."""

from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "codex_setup.py"
_spec = importlib.util.spec_from_file_location("codex_setup", SCRIPT)
assert _spec and _spec.loader
setup: Any = importlib.util.module_from_spec(_spec)
sys.modules["codex_setup"] = setup
_spec.loader.exec_module(setup)

THEIRS = """model = "gpt-5.5"
# my comment stays
[mcp_servers.other]
command = "npx"
args = ["-y", "other"]

[profiles.fast]
model_reasoning_effort = "low"
"""


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / ".codex"


@pytest.fixture
def python(tmp_path: Path) -> str:
    exe = tmp_path / "python.exe"
    exe.write_text("")
    return str(exe)


def run(*argv: str) -> int:
    return setup.main(list(argv))


def test_add_keeps_every_other_setting_and_never_writes_the_token(home: Path, python: str, tmp_path: Path) -> None:
    home.mkdir()
    (home / "config.toml").write_text(THEIRS, encoding="utf-8")
    token_file = tmp_path / "Recall Spring" / "codex-connector-token"
    assert run("config", "add", "--codex-home", str(home), "--python", python, "--token-file", str(token_file)) == 0
    text = (home / "config.toml").read_text(encoding="utf-8")
    assert text.startswith(THEIRS)  # byte for byte, comment included
    data = tomllib.loads(text)
    ours = data["mcp_servers"]["recallspring"]
    assert ours["command"] == python and ours["args"] == ["-m", "recallspring_mcp"]
    assert ours["default_tools_approval_mode"] == "writes" and ours["tool_timeout_sec"] == 120
    assert ours["env"] == {"RS_API_URL": "http://127.0.0.1:4318", "RS_CONNECTOR_TOKEN_FILE": str(token_file)}
    assert "rsc_" not in text
    assert (home / "config.toml.bak-before-recallspring").read_text(encoding="utf-8") == THEIRS
    assert run("config", "check", "--codex-home", str(home)) == 0

    # Running it again replaces the block instead of adding a second one; remove restores the file.
    assert run("config", "add", "--codex-home", str(home), "--python", python, "--approval", "prompt") == 0
    again = (home / "config.toml").read_text(encoding="utf-8")
    assert again.count(setup.BEGIN) == 1
    assert tomllib.loads(again)["mcp_servers"]["recallspring"]["default_tools_approval_mode"] == "prompt"
    assert run("config", "remove", "--codex-home", str(home)) == 0
    assert (home / "config.toml").read_text(encoding="utf-8") == THEIRS
    assert run("config", "check", "--codex-home", str(home)) == 1


def test_add_creates_a_missing_config(home: Path, python: str) -> None:
    assert run("config", "add", "--codex-home", str(home), "--python", python) == 0
    assert "recallspring" in tomllib.loads((home / "config.toml").read_text(encoding="utf-8"))["mcp_servers"]


def test_an_entry_recallspring_did_not_write_is_left_alone(home: Path, python: str) -> None:
    home.mkdir()
    mine = '[mcp_servers.recallspring]\ncommand = "my-own"\n'
    (home / "config.toml").write_text(mine, encoding="utf-8")
    assert run("config", "add", "--codex-home", str(home), "--python", python) == 2
    assert (home / "config.toml").read_text(encoding="utf-8") == mine


def test_invalid_toml_is_never_touched(home: Path, python: str) -> None:
    home.mkdir()
    broken = "model = \n[["
    (home / "config.toml").write_text(broken, encoding="utf-8")
    assert run("config", "add", "--codex-home", str(home), "--python", python) == 2
    assert (home / "config.toml").read_text(encoding="utf-8") == broken
    assert not (home / "config.toml.bak-before-recallspring").exists()


def test_inline_mcp_servers_table_is_refused_without_changes(home: Path, python: str) -> None:
    home.mkdir()
    inline = 'mcp_servers = { other = { command = "x" } }\n'
    (home / "config.toml").write_text(inline, encoding="utf-8")
    assert run("config", "add", "--codex-home", str(home), "--python", python) == 2
    assert (home / "config.toml").read_text(encoding="utf-8") == inline


def test_study_folders_are_read_only_and_keep_your_edits(tmp_path: Path, monkeypatch: Any) -> None:
    courses = [
        {"id": "11111111-aaaa", "title": "Statistika: 1/2", "kind": "course", "status": "active"},
        {"id": "22222222-bbbb", "title": "Statistika- 1-2", "kind": "course", "status": "active"},
        {"id": "33333333-cccc", "title": "Old", "kind": "course", "status": "archived"},
        {"id": "44444444-dddd", "title": "CON", "kind": "interest", "status": "active"},
    ]
    monkeypatch.setattr(setup, "fetch_courses", lambda _url, _token: courses)
    root = tmp_path / "Study"
    assert run("folders", "--root", str(root)) == 0
    names = sorted(p.name for p in root.iterdir())
    assert names == ["CON (course)", "Planning", "Statistika- 1-2", "Statistika- 1-2 (22222222)"]
    agents = (root / "Statistika- 1-2" / "AGENTS.md").read_text(encoding="utf-8")
    assert "course_id `11111111-aaaa`" in agents and "get_answer" in agents
    assert "interest" in (root / "CON (course)" / "AGENTS.md").read_text(encoding="utf-8")
    cfg = tomllib.loads((root / "Planning" / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert cfg == {"sandbox_mode": "read-only", "approval_policy": "on-request"}

    edited = root / "Planning" / "AGENTS.md"
    edited.write_text("My own planning rules.\n", encoding="utf-8")
    assert run("folders", "--root", str(root)) == 0
    assert edited.read_text(encoding="utf-8") == "My own planning rules.\n"
