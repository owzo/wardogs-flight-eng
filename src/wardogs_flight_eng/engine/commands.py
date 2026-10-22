"""Force-feedback effect commands emitted by the engine.

Magnitudes and coefficients are normalised 0..1, except ``PulseCommand.magnitude``
which is signed -1..1 (the sign is the push direction along the axis).
"""

from dataclasses import dataclass
from enum import StrEnum


class Axis(StrEnum):
    """Force-feedback stick axis an effect acts on."""

    PITCH = "pitch"
    ROLL = "roll"


@dataclass(frozen=True, slots=True)
class SpringCommand:
    """Centring spring about ``center`` with a ``deadband`` around it."""

    axis: Axis
    center: float
    coefficient: float
    deadband: float


@dataclass(frozen=True, slots=True)
class SineCommand:
    """Continuous sinusoidal vibration."""

    axis: Axis
    frequency_hz: float
    magnitude: float


@dataclass(frozen=True, slots=True)
class PulseCommand:
    """One-shot constant push of signed ``magnitude`` lasting ``duration_s``."""

    axis: Axis
    magnitude: float
    duration_s: float


@dataclass(frozen=True, slots=True)
class TransientCommand:
    """One-shot decaying vibration, faded out over the last ``blend_out_s``."""

    axis: Axis
    frequency_hz: float
    magnitude: float
    duration_s: float
    blend_out_s: float


@dataclass(frozen=True, slots=True)
class AllOffCommand:
    """Stop every active effect."""


Command = (
    SpringCommand | SineCommand | PulseCommand | TransientCommand | AllOffCommand
)
