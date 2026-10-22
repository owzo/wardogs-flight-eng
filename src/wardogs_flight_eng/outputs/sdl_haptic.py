"""SDL2 haptic force backend for the force-feedback stick base, and its probe."""

import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import partial
from typing import assert_never

from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Axis,
    Command,
    PulseCommand,
    SineCommand,
    SpringCommand,
    TransientCommand,
)
from wardogs_flight_eng.inputs.protocol import DeviceLostError
from wardogs_flight_eng.inputs.sdl_api import HapticEffect, SdlError
from wardogs_flight_eng.inputs.sdl_device import SdlDevice
from wardogs_flight_eng.outputs.sdl_channel import EffectPool, HapticChannel
from wardogs_flight_eng.outputs.sdl_effects import (
    advance_phase,
    milliseconds,
    period_ms,
    pulse_effect,
    silenced,
    sine_effect,
    spring_effect,
    transient_effect,
)
from wardogs_flight_eng.outputs.sdl_probe import PrimitiveReport, probe_primitives

__all__ = ["PrimitiveReport", "SdlHapticBackend", "probe_primitives"]

log = logging.getLogger(__name__)

IDLE_PERIOD_MS = 1000  # sine period until a positive frequency is commanded


@dataclass(slots=True)
class _Held:
    effect_id: int
    effect: HapticEffect


@dataclass(slots=True)
class _SineClock:
    period: int = IDLE_PERIOD_MS
    phase: int = 0
    t: float | None = None


class SdlHapticBackend:
    """``ForceBackend`` driving the haptic side of an opened ``SdlDevice``.

    Springs and sines are persistent: one effect per axis, created on first
    use, then updated in place and re-run every tick (never recreated). Their
    length is finite -- ``persistent_length_s`` (the CLI passes 2 x the
    profile's watchdog) -- and each tick's update + run restarts it, so if the
    loop freezes the base lets the forces time out instead of holding them.
    Because a run restarts a sine from its ``phase``, the phase is carried
    forward from tick to tick so the waveform stays continuous.

    Pulses (constant) and transients (fading sine) play from a pool of four
    slots per axis and kind; slots are destroyed in ``close``. A detached
    device raises ``DeviceLostError``; any other SDL failure ``SdlError``.
    """

    def __init__(self, device: SdlDevice, persistent_length_s: float = 1.0) -> None:
        if not (math.isfinite(persistent_length_s) and persistent_length_s > 0):
            raise ValueError(
                f"persistent_length_s must be positive, got {persistent_length_s!r}"
            )
        self._api = device.api
        self._channel = HapticChannel(device.api, device.joystick)
        self._length_ms = milliseconds(persistent_length_s)
        self._held: dict[tuple[str, Axis], _Held] = {}
        self._pools: dict[tuple[str, Axis], EffectPool] = {}
        self._sines: dict[Axis, _SineClock] = {}
        self._closed = False

    def apply(self, t: float, commands: Sequence[Command]) -> None:
        if self._closed:
            log.warning("apply ignored: haptic backend already closed")
            return
        self._channel.require_attached()
        for command in commands:
            self._dispatch(t, command)

    def all_off(self) -> None:
        """Stop every effect, then zero each persistent one.

        The zeroing means a later run cannot resurrect a force. Every step is
        attempted even if one fails; the first failure is raised afterwards.
        """
        if self._closed:
            return
        failures: list[DeviceLostError | SdlError] = []
        _attempt(failures, self._channel.stop_all)
        for held in self._held.values():
            held.effect = silenced(held.effect)
            _attempt(
                failures, partial(self._channel.update, held.effect_id, held.effect)
            )
        if failures:
            raise failures[0]

    def close(self) -> None:
        """``all_off``, destroy every effect, close the device; idempotent."""
        if self._closed:
            return
        try:
            self.all_off()
        finally:
            self._closed = True
            for effect_id in self._effect_ids():
                self._channel.destroy(effect_id)
            self._channel.close()

    def _dispatch(self, t: float, command: Command) -> None:
        match command:
            case AllOffCommand():
                self.all_off()
            case SpringCommand():
                effect = spring_effect(self._api, command, self._length_ms)
                self._hold("spring", command.axis, effect)
            case SineCommand():
                self._hold("sine", command.axis, self._sine(t, command))
            case PulseCommand():
                pool = self._pool("pulse", command.axis)
                pool.play(t, pulse_effect(self._api, command), command.duration_s)
            case TransientCommand():
                self._transient(t, command)
            case _:
                assert_never(command)

    def _hold(self, kind: str, axis: Axis, effect: HapticEffect) -> None:
        held = self._held.get((kind, axis))
        if held is None:
            held = _Held(self._channel.new(effect), effect)
            self._held[(kind, axis)] = held
        else:
            self._channel.update(held.effect_id, effect)
            held.effect = effect
        self._channel.run(held.effect_id)

    def _sine(self, t: float, command: SineCommand) -> HapticEffect:
        """The axis's sine; frequency 0 silences it and keeps the last period."""
        clock = self._sines.setdefault(command.axis, _SineClock())
        if clock.t is not None:
            clock.phase = advance_phase(clock.phase, t - clock.t, clock.period)
        clock.t = t
        period = period_ms(command.frequency_hz)
        if period is not None:
            clock.period = period
        return sine_effect(
            self._api,
            command.axis,
            period=clock.period,
            magnitude=command.magnitude if period is not None else 0.0,
            length_ms=self._length_ms,
            phase=clock.phase,
        )

    def _transient(self, t: float, command: TransientCommand) -> None:
        period = period_ms(command.frequency_hz)
        if period is None:
            log.debug("transient on %s with no frequency skipped", command.axis)
            return
        effect = transient_effect(self._api, command, period)
        self._pool("transient", command.axis).play(t, effect, command.duration_s)

    def _pool(self, kind: str, axis: Axis) -> EffectPool:
        return self._pools.setdefault((kind, axis), EffectPool(self._channel))

    def _effect_ids(self) -> list[int]:
        held = [entry.effect_id for entry in self._held.values()]
        return held + [i for pool in self._pools.values() for i in pool.effect_ids]


def _attempt(
    failures: list[DeviceLostError | SdlError], call: Callable[[], None]
) -> None:
    try:
        call()
    except (DeviceLostError, SdlError) as err:
        failures.append(err)
