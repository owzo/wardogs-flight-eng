"""Feel model: the stick's spring, friction, damper and inertia each tick.

``force_trim`` slews the spring centre to the trim anchor (``TrimState``) and
keeps every condition constant. ``unboosted`` keeps the spring centred and
lets trim-lock blend in a clamp: the spring fades out while friction rises to
``clamp_friction``, and trim-reset blends it back. The clamp blend moves at a
fixed rate of ``1 / trim_slew_s`` per second from wherever it is, unlike
``TrimState`` whose every move takes the full slew time.
"""

from wardogs_flight_eng.engine.commands import (
    Axis,
    Command,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
    SpringCommand,
)
from wardogs_flight_eng.engine.profile_sections import Feel
from wardogs_flight_eng.engine.trim import TrimState

_FREE = 0.0
_CLAMPED = 1.0


class _Blend:
    """A ``0..1`` value moving toward its target at ``1 / slew_s`` per second."""

    def __init__(self, slew_s: float) -> None:
        """Start free (value and target 0); ``slew_s`` 0 snaps on ``step``."""
        if slew_s < 0:
            raise ValueError(f"slew_s must be >= 0, got {slew_s}")
        self._slew_s = slew_s
        self.value = _FREE
        self._target = _FREE

    def retarget(self, target: float) -> None:
        """Head for ``target`` from the current value, with no jump."""
        self._target = target

    def step(self, dt: float) -> None:
        """Advance by ``dt`` seconds (negative counts as zero), never overshooting."""
        if self._slew_s == 0:
            self.value = self._target
            return
        delta = max(dt, 0.0) / self._slew_s
        if self._target >= self.value:
            self.value = min(self._target, self.value + delta)
        else:
            self.value = max(self._target, self.value - delta)
        self.value = max(_FREE, min(_CLAMPED, self.value))


class FeelModel:
    """Per-tick force-feedback conditions for pitch and roll from a ``Feel``."""

    def __init__(self, feel: Feel) -> None:
        """Create a model in its initial state: centred, clamp off."""
        self._feel = feel
        self._unboosted = feel.mode == "unboosted"
        self._trim = TrimState(feel.trim_slew_s)
        self._blend = _Blend(feel.trim_slew_s)

    @property
    def center_pitch(self) -> float:
        """Spring centre on pitch: the trim anchor, or 0 when unboosted."""
        return 0.0 if self._unboosted else self._trim.center_pitch

    @property
    def center_roll(self) -> float:
        """Spring centre on roll: the trim anchor, or 0 when unboosted."""
        return 0.0 if self._unboosted else self._trim.center_roll

    @property
    def clamp_blend(self) -> float:
        """Clamp blend ``0..1`` (always 0 in ``force_trim`` mode)."""
        return self._blend.value

    def lock(self, pitch: float, roll: float) -> None:
        """Trim-lock: anchor at the stick (force_trim) or clamp it (unboosted)."""
        if self._unboosted:
            self._blend.retarget(_CLAMPED)
            return
        self._trim.lock(pitch, roll)

    def reset(self) -> None:
        """Trim-reset: anchor to origin (force_trim) or free the stick (unboosted)."""
        if self._unboosted:
            self._blend.retarget(_FREE)
            return
        self._trim.reset()

    def step(self, dt: float) -> None:
        """Advance the anchor slew or the clamp blend by ``dt`` seconds."""
        if self._unboosted:
            self._blend.step(dt)
            return
        self._trim.step(dt)

    def restart(self) -> None:
        """Return to the initial state at once: centred, clamp off, no slew."""
        self._trim = TrimState(self._feel.trim_slew_s)
        self._blend = _Blend(self._feel.trim_slew_s)

    def conditions(self) -> list[Command]:
        """Spring, friction, damper and inertia, each pitch then roll."""
        feel = self._feel
        spring = feel.spring_coefficient
        friction = feel.friction
        if self._unboosted and feel.clamp_friction is not None:
            c = self._blend.value
            spring = spring * (1.0 - c)
            friction = friction + (feel.clamp_friction - friction) * c
        roll = feel.roll_scale
        return [
            SpringCommand(Axis.PITCH, self.center_pitch, spring, feel.deadband),
            SpringCommand(Axis.ROLL, self.center_roll, spring * roll, feel.deadband),
            FrictionCommand(Axis.PITCH, friction),
            FrictionCommand(Axis.ROLL, friction * roll),
            DamperCommand(Axis.PITCH, feel.damper),
            DamperCommand(Axis.ROLL, feel.damper),
            InertiaCommand(Axis.PITCH, feel.inertia),
            InertiaCommand(Axis.ROLL, feel.inertia),
        ]
