"""Set up RecallSpring for Google Antigravity (the Antigravity app and its CLI share one MCP config file).

``config add`` adds one ``recallspring`` entry to ``mcpServers`` in Antigravity's ``mcp_config.json`` and keeps
every other entry and setting: a one-time backup is made, and the result is parsed and compared before it replaces
the file. The token itself never goes into the config; the entry only names the file that holds it.

The entry is recognised as RecallSpring's by its ``recallspring_mcp`` module and ``RS_CONNECTOR_TOKEN_FILE``; an
entry called ``recallspring`` that looks different is left alone and the command stops.

    python -I scripts/antigravity_setup.py config add --python <repo>/services/mcp/.venv/Scripts/python.exe
    python -I scripts/antigravity_setup.py config remove
    python -I scripts/antigravity_setup.py config check

The study folders (one per course, each with an AGENTS.md that Antigravity and Codex both read) come from
``scripts/codex_setup.py folders``. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

NAME = "recallspring"
MODULE_ARGS = ["-m", "recallspring_mcp"]


def default_config() -> Path:
    return Path.home() / ".gemini" / "config" / "mcp_config.json"


def default_token_file() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) / "RecallSpring" if base else Path.home() / ".config" / "recallspring"
    return root / "antigravity-connector-token"


def entry(python: str, api_url: str, token_file: Path, timeout: int) -> dict[str, Any]:
    return {
        "command": python,
        "args": list(MODULE_ARGS),
        "env": {"RS_API_URL": api_url, "RS_CONNECTOR_TOKEN_FILE": str(token_file)},
        "timeoutSeconds": timeout,
    }


def is_ours(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("args") == MODULE_ARGS
        and isinstance(value.get("env"), dict)
        and "RS_CONNECTOR_TOKEN_FILE" in value["env"]
    )


def without_ours(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    servers = dict(out.get("mcpServers") or {})
    servers.pop(NAME, None)
    out["mcpServers"] = servers
    return out


def write_checked(path: Path, data: dict[str, Any], expected_rest: dict[str, Any]) -> None:
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if without_ours(json.loads(text)) != expected_rest:
        raise RuntimeError("the result would change other Antigravity settings")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-recallspring")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    json.loads(tmp.read_text(encoding="utf-8"))
    os.replace(tmp, path)


def config_command(args: argparse.Namespace) -> int:
    path: Path = args.config
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        current = json.loads(original) if original.strip() else {}
    except json.JSONDecodeError as exc:
        print(f"{path} is not valid JSON ({exc}); fix it in Antigravity first. Nothing was changed.", file=sys.stderr)
        return 2
    if not isinstance(current, dict) or not isinstance(current.get("mcpServers", {}), dict):
        print(f"{path} does not look like an MCP config (no mcpServers object). Nothing was changed.", file=sys.stderr)
        return 2
    servers = current.get("mcpServers") or {}
    present = NAME in servers
    if args.action == "check":
        print("present" if present and is_ours(servers[NAME]) else "absent")
        return 0 if present and is_ours(servers[NAME]) else 1
    if present and not is_ours(servers[NAME]):
        print(
            f'{path} already has an MCP server called "{NAME}" that RecallSpring did not write. Remove or rename it in '
            "Antigravity (Manage MCP Servers), then run this again. Nothing was changed.",
            file=sys.stderr,
        )
        return 2
    if args.action == "remove" and not present:
        print(f"remove: nothing to do ({path})")
        return 0

    if path.exists():
        backup = path.with_name(path.name + ".bak-before-recallspring")
        if not backup.exists():
            shutil.copy2(path, backup)
    rest = without_ours(current)
    new = json.loads(json.dumps(rest))
    if args.action == "add":
        if not args.python or not Path(args.python).is_file():
            print("--python must point to the connector's python.exe", file=sys.stderr)
            return 2
        new["mcpServers"][NAME] = entry(args.python, args.api_url, args.token_file, args.timeout)
    try:
        write_checked(path, new, rest)
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"Could not update {path}: {exc}. Nothing was changed.", file=sys.stderr)
        return 2
    print(f"{args.action}: done ({path})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="antigravity_setup")
    sub = parser.add_subparsers(dest="command", required=True)
    cfg = sub.add_parser("config")
    cfg.add_argument("action", choices=["add", "remove", "check"])
    cfg.add_argument("--config", type=Path, default=default_config(), help="Antigravity's mcp_config.json")
    cfg.add_argument("--python", help="absolute path of the connector's python.exe (for add)")
    cfg.add_argument("--api-url", default="http://127.0.0.1:4318")
    cfg.add_argument("--token-file", type=Path, default=default_token_file())
    cfg.add_argument("--timeout", type=int, default=300, help="timeoutSeconds (imports and page images)")
    args = parser.parse_args(argv)
    return config_command(args)


if __name__ == "__main__":
    raise SystemExit(main())
