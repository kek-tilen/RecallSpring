"""Add (or remove) the RecallSpring connector in Claude Desktop's ``claude_desktop_config.json``.

Only the ``mcpServers.recallspring`` entry is touched; every other key is preserved byte-for-byte in meaning.
A one-time backup is written next to the file. Run it while Claude Desktop is **closed**: the running app keeps
its settings in memory and rewrites the file, dropping external edits.

    python -I scripts/claude_desktop_config.py add  --config <path> --python <repo>/services/mcp/.venv/Scripts/python.exe
    python -I scripts/claude_desktop_config.py remove --config <path>
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

NAME = "recallspring"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp-recallspring")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))  # validate before replacing
    os.replace(tmp, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["add", "remove", "check"])
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--python", help="absolute path of the connector's python.exe (for add)")
    parser.add_argument("--api-url", default="http://127.0.0.1:4318")
    args = parser.parse_args()

    data = load(args.config)
    servers = data.get("mcpServers") or {}
    if args.action == "check":
        print("present" if NAME in servers else "absent")
        return 0 if NAME in servers else 1

    if args.config.exists():
        backup = args.config.with_name(args.config.name + ".bak-before-recallspring")
        if not backup.exists():
            shutil.copy2(args.config, backup)
    if args.action == "add":
        if not args.python or not Path(args.python).is_file():
            print("--python must point to the connector's python.exe", file=sys.stderr)
            return 2
        servers[NAME] = {"command": args.python, "args": ["-m", "recallspring_mcp"], "env": {"RS_API_URL": args.api_url}}
    else:
        servers.pop(NAME, None)
    others = {k: v for k, v in data.items() if k != "mcpServers"}
    data["mcpServers"] = servers
    save(args.config, data)
    after = load(args.config)
    assert {k: v for k, v in after.items() if k != "mcpServers"} == others
    print(f"{args.action}: done ({args.config})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
