"""Local settings for a new RecallSpring install (used by scripts/install.ps1; standard library only).

``env`` writes the two Git-ignored settings files a local install needs, only when they are missing:

- ``infra/.env``: a random password for the local database (Docker, loopback only);
- ``services/api/.env``: how the API reaches that database, local HTTP cookies and no simulated AI.

Existing files are never changed or overwritten, so running the installer again keeps your settings. The password
is never printed.

``check-python`` exits 0 when this Python is new enough.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

MIN_PYTHON = (3, 12)
DB_PORT = 55432


def _write_new(path: Path, text: str) -> bool:
    """Create ``path`` with ``text``; False (and nothing written) when it already exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as f:
            f.write(text)
    except FileExistsError:
        return False
    return True


def _password(infra_env: Path) -> str | None:
    for line in infra_env.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "RS_DEV_DB_PASSWORD" and value.strip():
            return value.strip()
    return None


def ensure_env(root: Path) -> list[str]:
    """Create the missing settings files under ``root``; returns what was created (relative paths)."""
    created = []
    infra_env = root / "infra" / ".env"
    # URL-safe letters only, so the password needs no escaping in the database URL.
    if _write_new(
        infra_env,
        "# Made by scripts/install.ps1. The password of your local database (Docker, 127.0.0.1 only).\n"
        f"RS_DEV_DB_PASSWORD={secrets.token_urlsafe(24)}\n",
    ):
        created.append("infra/.env")
    password = _password(infra_env)
    if password is None:
        raise SystemExit("infra/.env has no RS_DEV_DB_PASSWORD line. Add one (a long random value) and run again.")
    api_env = root / "services" / "api" / ".env"
    if _write_new(
        api_env,
        "# Made by scripts/install.ps1 for this computer. See services/api/.env.example for more settings.\n"
        "RS_ENVIRONMENT=development\n"
        f"RS_DATABASE_URL=postgresql+psycopg://recallspring:{password}@127.0.0.1:{DB_PORT}/recallspring\n"
        "# RecallSpring runs on http://127.0.0.1 only; keep true anywhere else.\n"
        "RS_COOKIE_SECURE=false\n"
        "# Backups go to local-data/backups (same disk). Another disk or a synced folder is safer, e.g.:\n"
        "# RS_BACKUP_DIR=D:/RecallSpring-backups\n",
    ):
        created.append("services/api/.env")
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="install_env")
    sub = parser.add_subparsers(dest="command", required=True)
    env = sub.add_parser("env")
    env.add_argument("--root", type=Path, required=True)
    sub.add_parser("check-python")
    args = parser.parse_args(argv)
    if args.command == "check-python":
        return 0 if sys.version_info[:2] >= MIN_PYTHON else 1
    created = ensure_env(args.root.resolve())
    for name in created:
        print(f"Created {name}")
    if not created:
        print("Settings files already exist; left unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
