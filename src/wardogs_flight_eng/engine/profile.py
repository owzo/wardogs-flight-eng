"""Airframe profile: owner-tuned feel, buzz, recoil and safety for one variant.

Profiles are hand-edited JSON. Every value here is owner taste (listed in
``taste``) or a pointer into the game constants (``airframe``,
``pilot_weapon``); game facts themselves live only in the constants file.
The section models live in ``profile_sections`` and are re-exported here.
"""

import json
from pathlib import Path
from typing import Any, Final, Self

from pydantic import ValidationError

from wardogs_flight_eng.constants.model import GameConstants
from wardogs_flight_eng.engine.device_map import (
    AxisBinding,
    AxisName,
    ButtonBinding,
    Calibration,
    DeviceMap,
    DeviceRef,
    ProfileModel,
)
from wardogs_flight_eng.engine.profile_sections import (
    Estimator,
    Feel,
    FeelMode,
    Recoil,
    Rotor,
    Safety,
)

__all__ = [
    "MIGRATION_HINT",
    "MIGRATION_HINT_FIELDS",
    "PROFILES_DIR",
    "AxisBinding",
    "AxisName",
    "ButtonBinding",
    "Calibration",
    "DeviceMap",
    "DeviceRef",
    "Estimator",
    "Feel",
    "FeelMode",
    "Profile",
    "ProfileError",
    "Recoil",
    "Rotor",
    "Safety",
    "load_profile",
]

PROFILES_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "profiles"
"""Directory holding the shipped airframe profiles."""

MIGRATION_HINT: Final[str] = (
    "this profile predates 0.2.0: copy the shipped profile for its airframe "
    "from the profiles directory, fill device_map and re-run calibrate"
)
"""Appended when one of ``MIGRATION_HINT_FIELDS`` is missing."""

MIGRATION_HINT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "feel.mode",
        "feel.friction",
        "feel.damper",
        "feel.inertia",
        "rotor.airspeed_factor",
        "estimator",
    }
)
"""The fields 0.2.0 added; a profile missing any of them predates 0.2.0."""


class ProfileError(ValueError):
    """A profile is unreadable, malformed, or names unknown game data."""


class Profile(ProfileModel):
    """One airframe variant with its single pilot weapon (or none)."""

    name: str
    airframe: str
    pilot_weapon: str | None
    verify_in_game: list[str]
    device_map: DeviceMap
    feel: Feel
    rotor: Rotor
    recoil: Recoil
    safety: Safety
    estimator: Estimator
    taste: list[str]

    @classmethod
    def from_document(cls, raw: dict[str, Any]) -> Self:
        """Validate a parsed profile document; failures become ``ProfileError``."""
        try:
            return cls.model_validate(raw)
        except ValidationError as err:
            raise ProfileError(_describe(err)) from err

    def validate_against(self, constants: GameConstants) -> None:
        """Raise ``ProfileError`` unless the airframe and weapon are game keys
        and no force gain exceeds ``safety.force_ceiling``."""
        self._check_gains_within_ceiling()
        if self.airframe not in constants.airframes:
            raise ProfileError(
                f"profile {self.name!r}: airframe {self.airframe!r} is not one of "
                f"{sorted(constants.airframes)}"
            )
        if self.pilot_weapon is not None and self.pilot_weapon not in (
            constants.weapons
        ):
            raise ProfileError(
                f"profile {self.name!r}: pilot_weapon {self.pilot_weapon!r} is not "
                f"one of {sorted(constants.weapons)}"
            )

    def _check_gains_within_ceiling(self) -> None:
        """Every gain the backend would clamp anyway is a profile error instead."""
        ceiling = self.safety.force_ceiling
        gains = {
            "feel.spring_coefficient": self.feel.spring_coefficient,
            "feel.friction": self.feel.friction,
            "feel.damper": self.feel.damper,
            "feel.inertia": self.feel.inertia,
            "rotor.base_amplitude": self.rotor.base_amplitude,
            "recoil.amplitude": self.recoil.amplitude,
            "recoil.shake_amplitude": self.recoil.shake_amplitude,
        }
        if self.feel.clamp_friction is not None:
            gains["feel.clamp_friction"] = self.feel.clamp_friction
        for field, value in gains.items():
            if value > ceiling:
                raise ProfileError(
                    f"profile {self.name!r}: {field} {value} is above "
                    f"safety.force_ceiling {ceiling}"
                )


def _describe(err: ValidationError) -> str:
    """Every validation failure as ``dotted.field: reason``, first failure first,
    plus the migration hint when one of ``MIGRATION_HINT_FIELDS`` is missing."""
    errors = err.errors()
    described = "; ".join(
        f"{'.'.join(str(part) for part in e['loc']) or '<document>'}: {e['msg']}"
        for e in errors
    )
    if any(
        e["type"] == "missing"
        and ".".join(str(part) for part in e["loc"]) in MIGRATION_HINT_FIELDS
        for e in errors
    ):
        return f"{described}; {MIGRATION_HINT}"
    return described


def load_profile(path: Path) -> Profile:
    """Read and validate the profile at ``path``; failures name file and field."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        raise ProfileError(f"cannot read profile {path}: {err.strerror}") from err
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as err:
        raise ProfileError(f"invalid profile {path}: {err}") from err
    try:
        return Profile.from_document(raw)
    except ProfileError as err:
        raise ProfileError(f"invalid profile {path}: {err}") from err
