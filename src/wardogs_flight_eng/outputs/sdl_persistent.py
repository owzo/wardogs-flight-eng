"""Persistent effects (springs, conditions, rotor sines): uploaded once, re-run rarely.

Every persistent effect has a finite length, so if the loop freezes the base
lets the force time out instead of holding it; staying alive therefore needs
a re-run before that length runs out. On Windows both
``SDL_HapticUpdateEffect`` and ``SDL_HapticRunEffect`` restart a playing
effect, so updating and running every persistent effect every tick restarts
it at the loop rate (about 800 restarts a second at 200 Hz for the two springs
and two sines alone).

``PersistentEffects`` instead uploads an effect only when it differs from the
held one (frozen-dataclass equality) and runs it only when it was just
uploaded, after ``all_off``, or once more than half its length has passed
since its last run: about two runs a second at the 1 s minimum length, which
keeps the finite-length safety alive. ``refresh_every_tick=True`` restores the
update-and-run on every tick, so the two can be compared on hardware.
"""

from dataclasses import dataclass
from functools import partial

from wardogs_flight_eng.engine.commands import Axis, SineCommand
from wardogs_flight_eng.inputs.sdl_api import HapticEffect, SdlApi
from wardogs_flight_eng.outputs.haptic_axes import HapticAxisMap
from wardogs_flight_eng.outputs.sdl_channel import HapticChannel, HapticFailure, attempt
from wardogs_flight_eng.outputs.sdl_effects import (
    advance_phase,
    period_ms,
    silenced,
    sine_effect,
)

IDLE_PERIOD_MS = 1000  # sine period until a positive frequency is commanded

EffectKey = tuple[str, Axis]


@dataclass(slots=True)
class _Held:
    effect_id: int
    effect: HapticEffect
    ran_at: float | None  # None: run on the next tick whatever it holds


@dataclass(slots=True)
class SineClock:
    """Where an axis's sine was when the device last (re)started it.

    A run (and, on Windows, an update) restarts the sine from the effect's
    ``phase``; starting it from the phase the waveform has reached since the
    previous start keeps the waveform continuous across restarts.
    """

    period: int = IDLE_PERIOD_MS
    phase: int = 0
    t: float | None = None

    def restart(self, t: float, period: int) -> int:
        """Re-anchor at ``t`` with ``period``; the phase to start the sine from."""
        if self.t is not None:
            self.phase = advance_phase(self.phase, t - self.t, self.period)
        self.t, self.period = t, period
        return self.phase


class PersistentEffects:
    """The held persistent effects of one haptic device, by kind and axis."""

    def __init__(
        self, channel: HapticChannel, length_s: float, *, refresh_every_tick: bool
    ) -> None:
        self._channel = channel
        self._rerun_after_s = length_s / 2
        self._refresh = refresh_every_tick
        self._held: dict[EffectKey, _Held] = {}

    @property
    def effect_ids(self) -> list[int]:
        return [held.effect_id for held in self._held.values()]

    def due(self, t: float, key: EffectKey, steady: HapticEffect) -> bool:
        """Whether ``key`` must be uploaded or run this tick.

        ``steady`` is the effect as it would be with nothing restarted. A held
        effect equal to it and run at most half a length ago is left playing.
        """
        held = self._held.get(key)
        if held is None or held.ran_at is None or self._refresh:
            return True
        return steady != held.effect or t - held.ran_at > self._rerun_after_s

    def play(self, t: float, key: EffectKey, effect: HapticEffect) -> None:
        """Upload ``effect`` if new or changed (every time when refreshing); run."""
        held = self._held.get(key)
        if held is None:
            held = _Held(self._channel.new(effect), effect, None)
            self._held[key] = held
        elif self._refresh or effect != held.effect:
            self._channel.update(held.effect_id, effect)
            held.effect = effect
        self._channel.run(held.effect_id)
        held.ran_at = t

    def silence(self, failures: list[HapticFailure]) -> None:
        """Zero every held effect so no later run resurrects a force.

        Each is due again on the next tick. A failing update is recorded in
        ``failures`` and the rest are still attempted.
        """
        for held in self._held.values():
            held.effect = silenced(held.effect)
            held.ran_at = None
            update = partial(self._channel.update, held.effect_id, held.effect)
            attempt(failures, update)


class PersistentSines:
    """Each axis's rotor sine, held in ``effects`` under ``("sine", axis)``."""

    def __init__(
        self,
        api: SdlApi,
        axes: HapticAxisMap,
        effects: PersistentEffects,
        length_ms: int,
    ) -> None:
        self._api = api
        self._axes = axes
        self._effects = effects
        self._length_ms = length_ms
        self._clocks: dict[Axis, SineClock] = {}

    def play(self, t: float, command: SineCommand) -> None:
        """The axis's sine; frequency 0 silences it and keeps the last period."""
        axis, key = command.axis, ("sine", command.axis)
        clock = self._clocks.setdefault(axis, SineClock())
        period = period_ms(command.frequency_hz)
        magnitude = command.magnitude if period is not None else 0.0
        period = clock.period if period is None else period
        steady = self._effect(axis, period, magnitude, clock.phase)
        if not self._effects.due(t, key, steady):
            return
        phase = clock.restart(t, period)
        self._effects.play(t, key, self._effect(axis, period, magnitude, phase))

    def _effect(
        self, axis: Axis, period: int, magnitude: float, phase: int
    ) -> HapticEffect:
        return sine_effect(
            self._api,
            self._axes,
            axis,
            period=period,
            magnitude=magnitude,
            length_ms=self._length_ms,
            phase=phase,
        )
