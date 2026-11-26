"""Running in the background (owner decision 2026-11-22): no console windows; logs go to rotating files and the
worker's heartbeat tells Settings whether it runs."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from recallspring_api import cli, runtime
from recallspring_api.ingest.jobs import run_worker

from .conftest import FrozenClock


@pytest.fixture(autouse=True)
def _fresh_heartbeat() -> Iterator[None]:
    runtime.heartbeat_path().unlink(missing_ok=True)
    yield
    runtime.heartbeat_path().unlink(missing_ok=True)


@pytest.fixture
def _keep_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level, hook = list(root.handlers), root.level, sys.excepthook
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    for h in handlers:
        root.addHandler(h)
    root.setLevel(level)
    sys.excepthook = hook


def test_the_heartbeat_says_whether_the_worker_runs(frozen: FrozenClock) -> None:
    assert runtime.worker_status() == {"state": "unknown", "last_seen": None}
    runtime.write_heartbeat()
    status = runtime.worker_status()
    assert status["state"] == "running" and status["last_seen"] == frozen().isoformat()
    frozen.advance(seconds=runtime.STALE_SECONDS + 1)
    assert runtime.worker_status()["state"] == "stopped"
    runtime.heartbeat_path().write_text("not json", encoding="utf-8")
    assert runtime.worker_status()["state"] == "unknown"


def test_the_worker_writes_a_heartbeat(frozen: FrozenClock) -> None:
    stops = iter([False, True])
    run_worker(poll_seconds=0, should_stop=lambda: next(stops))
    assert runtime.worker_status()["state"] == "running"


def test_readiness_reports_the_worker_without_depending_on_it(client: TestClient, frozen: FrozenClock) -> None:
    body = client.get("/api/v1/health/ready").json()
    assert body["status"] == "ready" and body["worker"] == {"state": "unknown", "last_seen": None}
    runtime.write_heartbeat()
    assert client.get("/api/v1/health/ready").json()["worker"]["state"] == "running"


def test_logs_go_to_a_rotating_file(tmp_path: Path, _keep_logging: None) -> None:
    path = tmp_path / "logs" / "api.log"
    runtime.log_to_file(path)
    logging.getLogger("uvicorn.error").warning("Številka 4318 je zasedena")
    (handler,) = logging.getLogger().handlers
    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert handler.maxBytes == runtime.LOG_MAX_BYTES and handler.backupCount == runtime.LOG_BACKUPS
    handler.flush()
    assert "WARNING uvicorn.error Številka 4318 je zasedena" in path.read_text(encoding="utf-8")


def test_serve_runs_uvicorn_without_its_console_logging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _keep_logging: None
) -> None:
    import uvicorn

    calls: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: calls.append((app, kw)))
    assert cli.main(["serve", "--log-file", str(tmp_path / "api.log")]) == 0
    assert calls == [("recallspring_api.main:app", {"host": "127.0.0.1", "port": 4318, "log_config": None})]
    assert cli.main(["serve", "--port", "4319"]) == 0
    assert calls[1] == ("recallspring_api.main:app", {"host": "127.0.0.1", "port": 4319})


def test_commands_read_the_api_env_from_any_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from recallspring_api import config

    api_env, local_env = config.Settings.model_config["env_file"]  # type: ignore[misc]
    assert api_env == Path(config.__file__).resolve().parents[2] / ".env" and local_env == ".env"
    (tmp_path / ".env").write_text("RS_SESSION_TTL_HOURS=7\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("RS_SESSION_TTL_HOURS", raising=False)
    assert config.Settings().session_ttl_hours == 7  # a .env in the current folder still wins
