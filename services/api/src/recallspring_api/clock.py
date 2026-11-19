"""Single source of 'now' so tests can move time deterministically."""

from __future__ import annotations

from datetime import UTC, datetime


def now() -> datetime:
    return datetime.now(UTC)
