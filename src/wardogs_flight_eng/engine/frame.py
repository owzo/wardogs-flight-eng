"""Per-tick control input consumed by the force-feedback engine."""

from dataclasses import dataclass
from enum import StrEnum


class Button(StrEnum):
    """Logical buttons the engine reacts to, independent of physical devices."""

    TRIM_LOCK = "trim_lock"
    TRIM_RESET = "trim_reset"
    FIRE = "fire"
    RELOAD = "reload"
    ROTOR_TOGGLE = "rotor_toggle"
    PROFILE_CYCLE = "profile_cycle"
    ALL_OFF = "all_off"


@dataclass(frozen=True, slots=True)
class ControlFrame:
    """One tick of normalised stick, collective and pedal state.

    ``pitch``, ``roll`` and ``pedals`` span -1..1; ``collective`` spans 0..1.
    ``held`` holds the buttons currently pressed.
    """

    pitch: float
    roll: float
    collective: float
    pedals: float
    held: frozenset[Button]

    def __post_init__(self) -> None:
        for name in ("pitch", "roll", "pedals"):
            if not -1.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be within -1..1")
        if not 0.0 <= self.collective <= 1.0:
            raise ValueError("collective must be within 0..1")
