"""IANA time zone names the learner may choose (tzdata ships with RecallSpring on every system)."""

from __future__ import annotations

import zoneinfo
from functools import lru_cache

from ..errors import ApiError


@lru_cache(maxsize=1)
def names() -> frozenset[str]:
    return frozenset(zoneinfo.available_timezones())


def check(name: str) -> str:
    if name not in names():
        raise ApiError(422, "invalid_timezone", "Choose a time zone from the list, e.g. Europe/Ljubljana.")
    return name
