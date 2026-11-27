"""Application settings, read from environment variables prefixed ``RS_`` (or a local ``.env``).

The ``.env`` of services/api is read from whichever folder a command runs in (e.g. ``recallspring shadow-report``
from the home folder); a ``.env`` in the current folder still overrides it, and environment variables override both.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[4]
_API_ENV = Path(__file__).resolve().parents[2] / ".env"  # services/api/.env (absent in an installed package)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RS_", env_file=(_API_ENV, ".env"), extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = Field(
        default="postgresql+psycopg://recallspring@127.0.0.1:55432/recallspring",
        description="SQLAlchemy URL. The password belongs in the environment, never in code.",
    )

    # Sessions and cookies
    cookie_secure: bool = True
    session_ttl_hours: int = 24
    login_max_failures: int = 5
    login_failure_window_seconds: int = 900

    # Learner defaults: accounts made with the CLI get this time zone (the first-run page uses the browser's).
    default_timezone: str = "UTC"
    # The first-run page may create the first account (only from this computer, only while none exists). Never in
    # production: there the account is made with the CLI.
    first_run_enabled: bool = True

    # Input bounds
    max_answer_chars: int = 20_000
    max_prompt_chars: int = 4_000
    max_note_chars: int = 200_000
    note_snapshot_window_seconds: int = 120

    # Sources (docs/08 → Files). Originals are stored privately under storage_dir, keyed by content hash.
    storage_dir: Path = _REPO_ROOT / "local-data" / "storage"
    # Upload limits per kind of file (docs/10 -> Upload limits). Documents carry pictures; text needs far less.
    max_upload_bytes: int = 100 * 1024 * 1024  # PDF, Word/PowerPoint/Excel, OpenDocument, notebooks
    max_text_upload_bytes: int = 10 * 1024 * 1024  # Markdown, text, CSV, subtitles, code, LaTeX
    max_image_upload_bytes: int = 20 * 1024 * 1024  # photos (Claude gets a smaller copy)
    max_library_bytes: int = 2 * 1024**3  # all originals of one learner (identical files count once)
    min_free_disk_bytes: int = 2 * 1024**3  # uploads pause before the disk, shared with other apps, runs low
    # Moving in (docs/08 -> Moving from ChatGPT): a ChatGPT data export or a ZIP of material is staged privately
    # under storage_dir/imports until the learner picks what to keep; unsaved uploads are removed after the
    # retention period. Each file inside still has the per-kind limits above.
    max_import_bytes: int = 1024**3
    # conversations.json is read whole: memory use is several times its size.
    max_import_json_bytes: int = 300 * 1024**2
    import_retention_days: int = Field(default=7, ge=1, le=60)
    max_pdf_pages: int = 600
    extraction_timeout_seconds: int = 120
    # "subprocess" isolates parser crashes and enforces the timeout; "inprocess" is only for fast tests.
    extraction_isolation: Literal["subprocess", "inprocess"] = "subprocess"
    # Optional page renderer (renderer.py, docs/08): LibreOffice turns Office/OpenDocument files into PDF pages so
    # Claude can look at whole slides and pages. "auto" uses it when installed; the path overrides the search.
    office_renderer: Literal["auto", "off"] = "auto"
    office_renderer_path: Path | None = None
    office_render_timeout_seconds: int = 120
    job_lease_seconds: int = 300
    job_max_attempts: int = 3

    # Backups (backup.py, docs/08 -> Backups): the worker makes one on schedule: a database dump plus the uploaded
    # files, checked by restoring it into a throwaway database.
    # backup_dir defaults to "backups" next to storage_dir, i.e. the same disk: point it at another disk or a
    # synced folder to survive a broken disk.
    backup_enabled: bool = True
    backup_dir: Path | None = None
    # A folder chosen in Settings → Data & backups replaces backup_dir; it is kept in this small file (never learner
    # data). backup_settings_from_web = false keeps the folder to the server settings (e.g. a hosted operator).
    backup_settings_file: Path = _REPO_ROOT / "local-data" / "backup-settings.json"
    backup_settings_from_web: bool = True
    # Schedule: every backup_every_days days at backup_time in the first account's time zone; Settings can choose
    # another (daily ... monthly, 2026-11-27). Daily backups keep the newest of each of backup_keep_daily days and
    # backup_keep_weekly weeks; less frequent ones keep the last backup_keep_last.
    backup_every_days: int = Field(default=1, ge=1, le=90)
    backup_time: str = Field(default="03:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    backup_keep_daily: int = Field(default=7, ge=1, le=90)
    backup_keep_weekly: int = Field(default=4, ge=0, le=52)
    backup_keep_last: int = Field(default=7, ge=1, le=90)
    backup_verify: bool = True
    backup_timeout_seconds: int = 600
    # pg_dump / pg_restore: in backup_pg_bin, else on PATH, else (development and test only) inside this container.
    backup_pg_bin: Path | None = None
    backup_docker_container: str | None = "recallspring-dev-db-1"

    # Web app: the built single-page app (apps/web/dist) is served by the API when present.
    web_dist: Path = _REPO_ROOT / "apps" / "web" / "dist"

    # Claude connector (Mode A): requests per learner-local day at 100 %; the owner scales it 1–100 %.
    connector_daily_requests_default: int = 600
    connector_note_chars: int = 8_000  # per note; keeps tool output (and Claude plan usage) small
    # Remote connector (2026-11-27): the address other computers use to reach this RecallSpring, such as
    # https://study.example.org, where the proxy sends /mcp to `recallspring-mcp --http` (services/mcp). Empty: the
    # connector works on this computer only. remote_from_internet: that address is reachable from the internet over
    # HTTPS on port 443, which Claude needs (it connects from Anthropic's cloud; Codex and Antigravity connect from
    # the computer they run on). Settings only shows these; opening an address is a step on the server and proxy.
    remote_url: str | None = Field(default=None, pattern=r"^https?://[^/\s]+$")
    remote_from_internet: bool = False

    # AI (Mode B). "none" disables in-app AI; "mock" is for development/tests and is always labelled Simulated.
    ai_evaluation_provider: Literal["none", "mock"] = "none"
    ai_question_provider: Literal["none", "mock"] = "none"
    ai_timeout_seconds: float = 90.0
    # Sign in with ChatGPT (ai/siwc.py, docs/04): only while RecallSpring runs on the learner's own computer (the
    # sign-in returns to http://127.0.0.1). Credentials stay in secrets_dir, outside the database and backups.
    chatgpt_signin_enabled: bool = True
    chatgpt_auth_base: str = "https://auth.openai.com"
    chatgpt_api_base: str = "https://api.openai.com/v1"
    secrets_dir: Path = _REPO_ROOT / "local-data" / "secrets"
    # Small runtime files, e.g. the worker heartbeat the API reads (runtime.py); never learner data.
    run_dir: Path = _REPO_ROOT / "local-data" / "run"
    ai_evaluation_lease_seconds: int = 180
    mock_ai_behavior: Literal["normal", "timeout", "error", "invalid"] = "normal"

    schemas_dir: Path = _REPO_ROOT / "packages" / "contracts" / "schemas"


@lru_cache
def get_settings() -> Settings:
    return Settings()
