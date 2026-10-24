"""Flight state seam: what the synthesiser knows about the aircraft.

The engine reads a ``FlightState`` each tick instead of the raw frame, so a
richer source (for example telemetry) can replace the input-only estimate
without touching the effects. ``InputEstimator`` is the default source: it
infers a normalised airspeed from sustained forward stick.
"""

import math
from dataclasses import dataclass
from typing import Protocol

from wardogs_flight_eng.engine.frame import ControlFrame


@dataclass(frozen=True, slots=True)
class FlightState:
    """Normalised aircraft state for one tick.

    ``airspeed`` and ``collective`` span 0..1; ``deflection`` is the cyclic's
    distance from the trim centre, 0..1.
    """

    airspeed: float
    collective: float
    deflection: float


class StateEstimator(Protocol):
    """Source of ``FlightState`` for the engine."""

    def step(self, dt: float, frame: ControlFrame, deflection: float) -> FlightState:
        """Advance by ``dt`` seconds and return the state for this tick."""
        ...

    def restart(self) -> None:
        """Forget accumulated state (for example on an all-off)."""
        ...


class InputEstimator:
    """Estimate airspeed as a first-order lag toward the forward-stick target.

    Pitch above ``forward_threshold`` (``+1`` is forward) maps linearly onto a
    ``0..1`` target airspeed; anything at or below it targets zero. The
    estimate approaches the target with time constant ``tau_s``; ``0`` snaps.
    """

    def __init__(self, forward_threshold: float, tau_s: float) -> None:
        """Create an estimator at rest (airspeed 0)."""
        if not 0.0 <= forward_threshold < 1.0:
            raise ValueError(
                f"forward_threshold must be >= 0 and < 1, got {forward_threshold}"
            )
        if tau_s < 0:
            raise ValueError(f"tau_s must be >= 0, got {tau_s}")
        self._forward_threshold = forward_threshold
        self._tau_s = tau_s
        self._airspeed = 0.0

    @property
    def airspeed(self) -> float:
        """Current airspeed estimate, ``0..1``."""
        return self._airspeed

    def step(self, dt: float, frame: ControlFrame, deflection: float) -> FlightState:
        """Advance the estimate by ``dt`` seconds (negative counts as zero)."""
        dt = max(dt, 0.0)
        target = self._target(frame.pitch)
        if self._tau_s == 0:
            self._airspeed = target
        else:
            blend = 1.0 - math.exp(-dt / self._tau_s)
            self._airspeed += (target - self._airspeed) * blend
        self._airspeed = max(0.0, min(1.0, self._airspeed))
        return FlightState(self._airspeed, frame.collective, deflection)

    def restart(self) -> None:
        """Reset the airspeed estimate to zero."""
        self._airspeed = 0.0

    def _target(self, pitch: float) -> float:
        """Airspeed the stick is asking for, ``0..1``."""
        span = 1.0 - self._forward_threshold
        return max(0.0, (pitch - self._forward_threshold) / span)
