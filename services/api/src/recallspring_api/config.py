"""Application settings, read from environment variables prefixed ``RS_`` (or a local ``.env``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RS_", env_file=".env", extra="ignore")

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

    # Learner defaults
    default_timezone: str = "Europe/Ljubljana"

    # Input bounds
    max_answer_chars: int = 20_000
    max_prompt_chars: int = 4_000

    # AI (Mode B). "none" disables in-app AI; "mock" is for development/tests and is always labelled Simulated.
    ai_evaluation_provider: Literal["none", "mock"] = "none"
    ai_question_provider: Literal["none", "mock"] = "none"
    ai_timeout_seconds: float = 90.0
    ai_evaluation_lease_seconds: int = 180
    mock_ai_behavior: Literal["normal", "timeout", "error", "invalid"] = "normal"

    schemas_dir: Path = _REPO_ROOT / "packages" / "contracts" / "schemas"


@lru_cache
def get_settings() -> Settings:
    return Settings()
