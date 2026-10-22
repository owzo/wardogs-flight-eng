"""Frozen game-derived constants. Unknown game values are ``None``, never guessed."""

from dataclasses import dataclass
from typing import Final

UNKNOWN: Final = "UNKNOWN - WARDOGS GAME VALUE REQUIRED"


def describe(value: float | int | None) -> str:
    """Render a constant for display; ``None`` becomes the UNKNOWN sentinel."""
    if value is None:
        return UNKNOWN
    return str(value)


@dataclass(frozen=True)
class Provenance:
    build_id: str
    extracted_at: str
    mappings: str


@dataclass(frozen=True)
class Airframe:
    key: str
    plugin: str
    mass_kg: float
    main_rotor_rpm: float
    rpm_source: str
    spool_down_rpm_per_s: float | None

    @property
    def one_per_rev_hz(self) -> float:
        """Main rotor rotation frequency in hertz."""
        return self.main_rotor_rpm / 60.0


@dataclass(frozen=True)
class Weapon:
    key: str
    asset: str
    rounds_per_minute: float
    windup_s: float
    reload_s: float
    reload_breakdown: tuple[float, ...]
    shake_multiplier: float | None
    shake: str | None
    recoil_pattern: tuple[tuple[float, float], ...]
    rounds_per_reload: int | None


@dataclass(frozen=True)
class Shake:
    key: str
    asset: str
    frequency_hz: float
    duration_s: float
    blend_in_s: float
    blend_out_s: float


@dataclass(frozen=True)
class InputFacts:
    pedal_heading_hold_threshold: float
    hotas_deadzone_default: float


@dataclass(frozen=True)
class GameConstants:
    provenance: Provenance
    airframes: dict[str, Airframe]
    weapons: dict[str, Weapon]
    shakes: dict[str, Shake]
    input: InputFacts
