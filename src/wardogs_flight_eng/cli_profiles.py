"""Profile files as the CLI uses them: load and check, rewrite calibration."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from wardogs_flight_eng.constants.model import GameConstants
from wardogs_flight_eng.engine.profile import (
    Calibration,
    Profile,
    ProfileError,
    load_profile,
)

log = logging.getLogger(__name__)


def load_checked_profile(path: Path, constants: GameConstants) -> Profile:
    """Load ``path`` and check its airframe and weapon are game keys."""
    profile = load_profile(path)
    profile.validate_against(constants)
    return profile


def write_calibration(path: Path, calibration: Calibration) -> None:
    """Replace only ``device_map.calibration`` in the profile file at ``path``.

    Every other field keeps its value and key order. The new document is
    validated before it replaces the file, and the replace is atomic, so a
    failure leaves the original profile untouched.
    """
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    document["device_map"]["calibration"] = calibration.model_dump()
    text = json.dumps(document, indent=2, ensure_ascii=False) + "\n"
    try:
        Profile.from_document(json.loads(text))
    except ProfileError as err:
        raise ProfileError(f"calibrated profile {path} would not load: {err}") from err
    staging = path.with_name(f"{path.name}.tmp")
    staging.write_text(text, encoding="utf-8")
    os.replace(staging, path)
    log.info("calibration written to %s", path)
