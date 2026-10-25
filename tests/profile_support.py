"""Shipped-profile paths and raw JSON access for the profile tests."""

import json
from typing import Any

from wardogs_flight_eng.engine.profile import PROFILES_DIR

PROFILES = PROFILES_DIR


def raw_profile(name: str) -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(
        (PROFILES / f"{name}.json").read_text(encoding="utf-8")
    )
    return raw
