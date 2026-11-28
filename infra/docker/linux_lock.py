"""Make a Linux copy of a pip-compile lock file by leaving out the packages that only Windows needs.

The lock files are compiled on Windows, where the MCP library also pulls in pywin32 (it asks for it only on Windows).
Hashes and versions of every other package stay exactly as they are. Used by infra/docker/Dockerfile:

    python linux_lock.py <requirements.lock> <output>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

WINDOWS_ONLY = {"pywin32", "pywin32-ctypes", "colorama"}
REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==")


def linux_lock(text: str) -> tuple[str, list[str]]:
    out: list[str] = []
    dropped: list[str] = []
    skipping = False
    for line in text.splitlines():
        match = REQUIREMENT.match(line)
        if match:
            name = match.group(1).lower().replace("_", "-")
            skipping = name in WINDOWS_ONLY
            if skipping:
                dropped.append(name)
                continue
        elif line and not line.startswith((" ", "\t")):
            skipping = False  # a comment or blank line at the left edge ends the block
        if not skipping:
            out.append(line)
    return "\n".join(out) + "\n", dropped


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    text, dropped = linux_lock(Path(argv[1]).read_text(encoding="utf-8"))
    Path(argv[2]).write_text(text, encoding="utf-8")
    print(f"Linux lock written to {argv[2]}; left out: {', '.join(dropped) or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
