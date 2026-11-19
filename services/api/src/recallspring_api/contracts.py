"""Shared JSON-schema contracts (packages/contracts/schemas)."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import Draft202012Validator

from .config import get_settings


@lru_cache
def load_schema(name: str) -> dict[str, Any]:
    path = get_settings().schemas_dir / name
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache
def validator(name: str) -> Draft202012Validator:
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema_errors(name: str, instance: Any) -> list[str]:
    """Sanitized validation messages: JSON paths and validator names only, never instance values."""
    errors = sorted(validator(name).iter_errors(instance), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.validator}" for e in errors]
