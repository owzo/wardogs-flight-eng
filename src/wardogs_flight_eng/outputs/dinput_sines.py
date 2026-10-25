"""Each axis's rotor sine on the DirectInput base, held with its phase carried.

A sine effect starts from its ``dwPhase``. ``PhaseClock`` follows the
waveform the device is playing: the phase it had at its anchor time and the
period it has run at since. Every time ``HeldSines`` sends the sine, the
effect carries the phase the waveform has reached by then (``reached``), and
the clock is anchored there with the new period:

- when the send (re)started the effect (``HeldEffects.restarted``: creation,
  a start after ``all_off`` or at the half-life, or a restarting update), the
  device restarts from exactly that phase, so the waveform stays continuous;
- when the send was an in-place update, the waveform keeps playing through
  it, so its phase at that instant is the reached phase anyway and anchoring
  there only moves the clock onto the new period from that instant on.

Both cases anchor the same way, and the phase must be in the effect before
the send (a refused in-place update is retried as a restart inside
``HeldEffects``), so ``HeldEffects.restarted`` is not consulted. Anchoring at
every send also keeps the held effect equal to the steady effect ``due``
compares it with, so an unchanged sine is sent again only at its half-life or
after ``all_off``.
"""

import math
from dataclasses import dataclass

from wardogs_flight_eng.engine.commands import Axis, SineCommand
from wardogs_flight_eng.inputs.dinput_api import DiEffect
from wardogs_flight_eng.outputs.dinput_effects import PHASE_TURN, period_us, sine_effect
from wardogs_flight_eng.outputs.dinput_persistent import HeldEffects
from wardogs_flight_eng.outputs.haptic_axes import HapticAxisMap

IDLE_PERIOD_US = 1_000_000  # sine period until a positive frequency is commanded


def advance_phase(phase: int, elapsed_s: float, period: int) -> int:
    """Phase after ``elapsed_s`` of a sine with ``period`` µs, wrapped to a turn."""
    if not math.isfinite(elapsed_s) or elapsed_s <= 0:
        return phase
    return round(phase + PHASE_TURN * elapsed_s * 1_000_000 / period) % PHASE_TURN


@dataclass(slots=True)
class PhaseClock:
    """Where an axis's sine waveform was at ``t`` and the period it runs at."""

    period: int = IDLE_PERIOD_US
    phase: int = 0
    t: float | None = None

    def reached(self, t: float) -> int:
        """The phase the waveform has reached at ``t``."""
        if self.t is None:
            return self.phase
        return advance_phase(self.phase, t - self.t, self.period)

    def anchor(self, t: float, period: int, phase: int) -> None:
        self.t, self.period, self.phase = t, period, phase


class HeldSines:
    """Each axis's rotor sine, held in ``held`` under ``("sine", axis)``."""

    def __init__(self, axes: HapticAxisMap, held: HeldEffects, length_us: int) -> None:
        self._axes = axes
        self._held = held
        self._length_us = length_us
        self._clocks: dict[Axis, PhaseClock] = {}

    def play(self, t: float, command: SineCommand) -> None:
        """The axis's sine; frequency 0 silences it and keeps the last period."""
        axis, key = command.axis, ("sine", command.axis)
        clock = self._clocks.setdefault(axis, PhaseClock())
        period = period_us(command.frequency_hz)
        magnitude = command.magnitude if period is not None else 0.0
        period = clock.period if period is None else period
        steady = self._effect(axis, period, magnitude, clock.phase)
        if not self._held.due(t, key, steady):
            return
        phase = clock.reached(t)
        self._held.play(t, key, self._effect(axis, period, magnitude, phase))
        clock.anchor(t, period, phase)

    def _effect(
        self, axis: Axis, period: int, magnitude: float, phase: int
    ) -> DiEffect:
        return sine_effect(
            self._axes,
            axis,
            period_us=period,
            magnitude=magnitude,
            length_us=self._length_us,
            phase=phase,
        )
