"""SDL2 haptic force backend for the force-feedback stick base, and its probe."""

import logging
import math
from collections.abc import Sequence
from typing import assert_never

from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Axis,
    Command,
    ConditionCommand,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
    PulseCommand,
    SineCommand,
    SpringCommand,
    TransientCommand,
)
from wardogs_flight_eng.inputs.sdl_device import SdlDevice
from wardogs_flight_eng.outputs.haptic_axes import HapticAxisMap
from wardogs_flight_eng.outputs.sdl_capabilities import (
    ConditionSupport,
    condition_kind,
)
from wardogs_flight_eng.outputs.sdl_channel import (
    EffectPool,
    HapticChannel,
    HapticFailure,
    attempt,
)
from wardogs_flight_eng.outputs.sdl_conditions import condition_effect, spring_effect
from wardogs_flight_eng.outputs.sdl_effects import (
    milliseconds,
    period_ms,
    pulse_effect,
    transient_effect,
)
from wardogs_flight_eng.outputs.sdl_persistent import (
    PersistentEffects,
    PersistentSines,
)
from wardogs_flight_eng.outputs.sdl_probe import PrimitiveReport, probe_primitives

__all__ = ["PrimitiveReport", "SdlHapticBackend", "probe_primitives"]

log = logging.getLogger(__name__)


class SdlHapticBackend:
    """``ForceBackend`` driving the haptic side of an opened ``SdlDevice``.

    Commands arrive in frame space -- the stick as the engine sees it, already
    inverted by the input bindings. ``axis_map`` (built from those bindings,
    required) undoes that: it picks each axis's haptic index and flips the
    spring centre and pulse level of an inverted axis.

    Springs, sines and the friction, damper and inertia conditions are
    persistent: one effect per kind and axis, created on first use and never
    recreated. Their length is finite -- ``persistent_length_s``
    (the CLI passes 2 x the profile's watchdog, at least 1 s) -- so if the
    loop freezes the base lets the forces time out instead of holding them.
    By default (``refresh_every_tick=False``) an effect is updated only when
    the command changes it, and run only after an update, after ``all_off``,
    or once half its length has passed since its last run (~2 runs/s at 1 s):
    on Windows every update or run restarts a playing effect.
    ``refresh_every_tick=True`` is the earlier behaviour -- update and run
    every persistent effect every tick -- kept so a hardware pass can A/B the
    two. A restarted sine starts from the phase its waveform has reached, so
    it stays continuous in both modes (``sdl_persistent.SineClock``).

    A condition kind the base does not report (``missing_conditions``; all
    three when the query returns 0) is dropped after one WARNING.

    Pulses (constant) and transients (fading sine) play from a pool of four
    slots per axis and kind; slots are destroyed in ``close``. A detached
    device raises ``DeviceLostError``; any other SDL failure ``SdlError``.
    """

    def __init__(
        self,
        device: SdlDevice,
        persistent_length_s: float = 1.0,
        *,
        axis_map: HapticAxisMap,
        refresh_every_tick: bool = False,
    ) -> None:
        if not (math.isfinite(persistent_length_s) and persistent_length_s > 0):
            raise ValueError(
                f"persistent_length_s must be positive, got {persistent_length_s!r}"
            )
        self._api = device.api
        self._axes = axis_map
        self._channel = HapticChannel(device.api, device.joystick)
        self._support = ConditionSupport.from_channel(device.api, self._channel)
        self._length_ms = milliseconds(persistent_length_s)
        self._persistent = PersistentEffects(
            self._channel,
            persistent_length_s,
            refresh_every_tick=refresh_every_tick,
        )
        self._sines = PersistentSines(
            device.api, axis_map, self._persistent, self._length_ms
        )
        self._pools: dict[tuple[str, Axis], EffectPool] = {}
        self._closed = False

    @property
    def missing_conditions(self) -> frozenset[str]:
        """Condition kinds the base does not report; their commands are dropped."""
        return self._support.missing

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
        failures: list[HapticFailure] = []
        attempt(failures, self._channel.stop_all)
        self._persistent.silence(failures)
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
                effect = spring_effect(self._api, self._axes, command, self._length_ms)
                if self._persistent.due(t, ("spring", command.axis), effect):
                    self._persistent.play(t, ("spring", command.axis), effect)
            case SineCommand():
                self._sines.play(t, command)
            case PulseCommand():
                pool = self._pool("pulse", command.axis)
                effect = pulse_effect(self._api, self._axes, command)
                pool.play(t, effect, command.duration_s)
            case TransientCommand():
                self._transient(t, command)
            case FrictionCommand() | DamperCommand() | InertiaCommand():
                self._condition(t, command)
            case _:
                assert_never(command)

    def _condition(self, t: float, command: ConditionCommand) -> None:
        """Friction, damper or inertia, unless the base lacks that kind."""
        if not self._support.allows(command):
            return
        effect = condition_effect(self._api, self._axes, command, self._length_ms)
        key = (condition_kind(command), command.axis)
        if self._persistent.due(t, key, effect):
            self._persistent.play(t, key, effect)

    def _transient(self, t: float, command: TransientCommand) -> None:
        period = period_ms(command.frequency_hz)
        if period is None:
            log.debug("transient on %s with no frequency skipped", command.axis)
            return
        effect = transient_effect(self._api, self._axes, command, period)
        self._pool("transient", command.axis).play(t, effect, command.duration_s)

    def _pool(self, kind: str, axis: Axis) -> EffectPool:
        return self._pools.setdefault((kind, axis), EffectPool(self._channel))

    def _effect_ids(self) -> list[int]:
        pooled = [i for pool in self._pools.values() for i in pool.effect_ids]
        return self._persistent.effect_ids + pooled
