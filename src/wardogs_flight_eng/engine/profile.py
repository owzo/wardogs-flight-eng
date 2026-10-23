"""Airframe profile: owner-tuned feel, buzz, recoil and safety for one variant.

Profiles are hand-edited JSON. Every value here is owner taste (listed in
``taste``) or a pointer into the game constants (``airframe``,
``pilot_weapon``); game facts themselves live only in the constants file.
"""

from pathlib import Path
from typing import Annotated, Final

from pydantic import Field, ValidationError

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

__all__ = [
    "PROFILES_DIR",
    "AxisBinding",
    "AxisName",
    "ButtonBinding",
    "Calibration",
    "DeviceMap",
    "DeviceRef",
    "Feel",
    "Profile",
    "ProfileError",
    "Recoil",
    "Rotor",
    "Safety",
    "load_profile",
]

PROFILES_DIR: Final[Path] = Path(__file__).resolve().parents[1] / "profiles"
"""Directory holding the shipped airframe profiles."""

Unit = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
SignedUnit = Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class ProfileError(ValueError):
    """A profile is unreadable, malformed, or names unknown game data."""


class Feel(ProfileModel):
    """Centring spring. The roll spring is ``spring_coefficient * roll_scale``."""

    spring_coefficient: Unit
    roll_scale: Unit = 0.5
    deadband: Unit
    trim_slew_s: NonNegative


class Rotor(ProfileModel):
    """Rotor buzz. ``None`` spool-down falls back to the airframe's constant."""

    base_amplitude: Unit
    deflection_factor: NonNegative
    spool_up_s: NonNegative
    spool_down_rpm_per_s: Positive | None


class Recoil(ProfileModel):
    """Recoil pulse gain, ``(roll, pitch)`` rocket kick and shake magnitude."""

    amplitude: Unit
    rocket_kick: tuple[SignedUnit, SignedUnit]
    shake_amplitude: Unit


class Safety(ProfileModel):
    """Backend force ceiling and the engine's stalled-tick watchdog."""

    force_ceiling: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)] = 0.6
    watchdog_s: Positive = 0.25


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
    taste: list[str]

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
            "rotor.base_amplitude": self.rotor.base_amplitude,
            "recoil.amplitude": self.recoil.amplitude,
            "recoil.shake_amplitude": self.recoil.shake_amplitude,
        }
        for field, value in gains.items():
            if value > ceiling:
                raise ProfileError(
                    f"profile {self.name!r}: {field} {value} is above "
                    f"safety.force_ceiling {ceiling}"
                )


def _describe(err: ValidationError) -> str:
    """Every validation failure as ``dotted.field: reason``, first failure first."""
    return "; ".join(
        f"{'.'.join(str(part) for part in e['loc']) or '<document>'}: {e['msg']}"
        for e in err.errors()
    )


def load_profile(path: Path) -> Profile:
    """Read and validate the profile at ``path``; failures name file and field."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        raise ProfileError(f"cannot read profile {path}: {err.strerror}") from err
    try:
        return Profile.model_validate_json(text)
    except ValidationError as err:
        raise ProfileError(f"invalid profile {path}: {_describe(err)}") from err
