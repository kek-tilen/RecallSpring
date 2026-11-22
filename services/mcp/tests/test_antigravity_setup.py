"""scripts/antigravity_setup.py: RecallSpring's entry in Antigravity's mcp_config.json."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "antigravity_setup.py"
_spec = importlib.util.spec_from_file_location("antigravity_setup", SCRIPT)
assert _spec and _spec.loader
setup: Any = importlib.util.module_from_spec(_spec)
sys.modules["antigravity_setup"] = setup
_spec.loader.exec_module(setup)

THEIRS = {
    "mcpServers": {"github": {"serverUrl": "https://example.invalid/mcp", "disabled": True}},
    "somethingElse": [1, 2, 3],
}


@pytest.fixture
def config(tmp_path: Path) -> Path:
    return tmp_path / ".gemini" / "config" / "mcp_config.json"


@pytest.fixture
def python(tmp_path: Path) -> str:
    exe = tmp_path / "python.exe"
    exe.write_text("")
    return str(exe)


def run(config: Path, *args: str) -> int:
    return setup.main(["config", *args, "--config", str(config)])


def test_add_keeps_other_servers_and_never_writes_the_token(config: Path, python: str, tmp_path: Path) -> None:
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps(THEIRS), encoding="utf-8")
    token = tmp_path / "antigravity-connector-token"
    token.write_text("rsct_secret_value")
    assert run(config, "add", "--python", python, "--token-file", str(token)) == 0
    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["mcpServers"]["github"] == THEIRS["mcpServers"]["github"] and data["somethingElse"] == [1, 2, 3]
    ours = data["mcpServers"]["recallspring"]
    assert ours["command"] == python and ours["args"] == ["-m", "recallspring_mcp"]
    assert ours["env"]["RS_CONNECTOR_TOKEN_FILE"] == str(token) and ours["timeoutSeconds"] == 300
    assert "rsct_secret_value" not in config.read_text(encoding="utf-8")
    assert json.loads((config.parent / "mcp_config.json.bak-before-recallspring").read_text()) == THEIRS
    assert run(config, "check") == 0

    assert run(config, "add", "--python", python, "--api-url", "http://127.0.0.1:9999") == 0  # replaced, not doubled
    assert json.loads(config.read_text())["mcpServers"]["recallspring"]["env"]["RS_API_URL"] == "http://127.0.0.1:9999"

    assert run(config, "remove") == 0
    assert json.loads(config.read_text(encoding="utf-8")) == THEIRS
    assert run(config, "check") == 1
    assert run(config, "remove") == 0  # nothing to do


def test_add_creates_a_missing_config(config: Path, python: str) -> None:
    assert run(config, "add", "--python", python) == 0
    assert list(json.loads(config.read_text())["mcpServers"]) == ["recallspring"]


def test_an_entry_recallspring_did_not_write_is_left_alone(config: Path, python: str) -> None:
    config.parent.mkdir(parents=True)
    theirs = {"mcpServers": {"recallspring": {"command": "npx", "args": ["something-else"]}}}
    config.write_text(json.dumps(theirs), encoding="utf-8")
    assert run(config, "add", "--python", python) == 2
    assert run(config, "remove") == 2
    assert run(config, "check") == 1
    assert json.loads(config.read_text()) == theirs


@pytest.mark.parametrize("text", ["{not json", "[1, 2]", '{"mcpServers": []}'])
def test_a_broken_config_is_never_touched(config: Path, python: str, text: str) -> None:
    config.parent.mkdir(parents=True)
    config.write_text(text, encoding="utf-8")
    assert run(config, "add", "--python", python) == 2
    assert config.read_text(encoding="utf-8") == text
    assert not (config.parent / "mcp_config.json.bak-before-recallspring").exists()


def test_add_needs_the_connector_python(config: Path, tmp_path: Path) -> None:
    assert run(config, "add", "--python", str(tmp_path / "missing.exe")) == 2
    assert not config.exists()
