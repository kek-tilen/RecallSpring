"""Running RecallSpring in the background (docs/install-windows.md → Running in the background).

The API and the worker run without a window; what they used to print goes to rotating log files instead
(local-data/logs by default; scripts/logs.ps1 shows them). The worker writes a small heartbeat file so the API can
tell whether it is running (health/ready → worker, shown in Settings). Nothing here calls a model.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType
from typing import Any

from . import clock
from .config import get_settings

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUPS = 3  # api.log, api.log.1 … api.log.3: at most about 20 MB per program
HEARTBEAT_SECONDS = 30
STALE_SECONDS = 120  # four missed heartbeats: the worker is not running

log = logging.getLogger("recallspring.runtime")


def log_to_file(path: Path) -> None:
    """Send all logging (uvicorn's included, which propagates to the root logger) to a rotating UTF-8 file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    def crashed(kind: type[BaseException], value: BaseException, tb: TracebackType | None) -> None:
        logging.getLogger("recallspring").critical("stopped after an unexpected error", exc_info=(kind, value, tb))

    sys.excepthook = crashed


def heartbeat_path() -> Path:
    return get_settings().run_dir / "worker-heartbeat.json"


def write_heartbeat() -> None:
    """Record that the worker is alive; a failure is logged, never raised (the worker keeps working)."""
    path = heartbeat_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"at": clock.now().isoformat(), "pid": os.getpid()}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("could not write the worker heartbeat: %s", exc)


def worker_status() -> dict[str, Any]:
    """running: a heartbeat within STALE_SECONDS; stopped: an older one; unknown: never seen (e.g. a new install
    or a worker on another machine)."""
    try:
        data = json.loads(heartbeat_path().read_text(encoding="utf-8"))
        seen = datetime.fromisoformat(data["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return {"state": "unknown", "last_seen": None}
    age = (clock.now() - seen).total_seconds()
    return {"state": "running" if age <= STALE_SECONDS else "stopped", "last_seen": seen.isoformat()}
