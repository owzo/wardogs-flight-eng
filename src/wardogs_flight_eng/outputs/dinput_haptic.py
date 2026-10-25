"""DirectInput 8 force backend for the force-feedback stick base."""

import logging
import math
from collections.abc import Sequence
from functools import partial
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
from wardogs_flight_eng.inputs.dinput_device import DInputJoystick
from wardogs_flight_eng.outputs.dinput_capabilities import DInputConditionSupport
from wardogs_flight_eng.outputs.dinput_channel import (
    DInputChannel,
    DInputPool,
    ForceFailure,
    attempt,
)
from wardogs_flight_eng.outputs.dinput_effects import (
    condition_effect,
    condition_kind,
    microseconds,
    period_us,
    pulse_effect,
    sine_effect,
    spring_effect,
)
from wardogs_flight_eng.outputs.dinput_persistent import HeldEffects
from wardogs_flight_eng.outputs.dinput_sines import HeldSines
from wardogs_flight_eng.outputs.haptic_axes import HapticAxisMap

__all__ = ["DInputHapticBackend"]

log = logging.getLogger(__name__)


class DInputHapticBackend:
    """``ForceBackend`` driving the force side of an acquired ``DInputJoystick``.

    The twin of ``SdlHapticBackend``: commands arrive in frame space and
    ``axis_map`` places each on its device axis. Springs, sines and the
    friction, damper and inertia conditions are held effects (one per kind and
    axis) of finite length ``persistent_length_s``, updated in place when they
    change and started again only after ``all_off`` or at their half-life
    (``HeldEffects``); a sine carries its phase (``HeldSines``). A condition
    kind the base does not report (``missing_conditions``) is dropped; its
    WARNING is logged here, at construction. Pulses and transients play from
    a pool of four effects per kind and axis.

    Device loss is noticed by the input poll; a force call on a lost device
    raises ``DeviceLostError``, any other failure ``DInputError``. ``close``
    releases every effect, then the device and the DirectInput object.
    """

    def __init__(
        self,
        joystick: DInputJoystick,
        persistent_length_s: float,
        *,
        axis_map: HapticAxisMap,
    ) -> None:
        if not (math.isfinite(persistent_length_s) and persistent_length_s > 0):
            raise ValueError(
                f"persistent_length_s must be positive, got {persistent_length_s!r}"
            )
        self._joystick = joystick
        self._axes = axis_map
        self._channel = DInputChannel(joystick.api, joystick.handle)
        self._support = DInputConditionSupport.from_device(
            joystick.api, joystick.handle
        )
        self._length_us = microseconds(persistent_length_s)
        self._held = HeldEffects(self._channel, persistent_length_s)
        self._sines = HeldSines(axis_map, self._held, self._length_us)
        self._pools: dict[tuple[str, Axis], DInputPool] = {}
        self._closed = False

    @property
    def missing_conditions(self) -> frozenset[str]:
        """Condition kinds the base does not report; their commands are dropped."""
        return self._support.missing

    def apply(self, t: float, commands: Sequence[Command]) -> None:
        if self._closed:
            log.warning("apply ignored: DirectInput backend already closed")
            return
        for command in commands:
            self._dispatch(t, command)

    def all_off(self) -> None:
        """Stop every effect, then zero each held one.

        The zeroing means a later start cannot resurrect a force. Every step is
        attempted even if one fails; the first failure is raised afterwards.
        """
        if self._closed:
            return
        failures: list[ForceFailure] = []
        attempt(failures, self._channel.stop_all)
        self._held.silence(failures)
        if failures:
            raise failures[0]

    def close(self) -> None:
        """``all_off``, release every effect, the device and DirectInput; idempotent."""
        if self._closed:
            return
        try:
            self.all_off()
        finally:
            self._closed = True
            self._release()

    def _release(self) -> None:
        """Release every effect, then the device and DirectInput.

        Each effect release is attempted even if an earlier one fails, and the
        device and DirectInput are released whatever happens; the first
        effect-release failure is raised afterwards.
        """
        failures: list[ForceFailure] = []
        try:
            for effect_id in self._effect_ids():
                attempt(failures, partial(self._channel.release, effect_id))
        finally:
            try:
                self._joystick.close()
            finally:
                self._joystick.api.close()
        if failures:
            raise failures[0]

    def _dispatch(self, t: float, command: Command) -> None:
        match command:
            case AllOffCommand():
                self.all_off()
            case SpringCommand():
                effect = spring_effect(self._axes, command, self._length_us)
                if self._held.due(t, ("spring", command.axis), effect):
                    self._held.play(t, ("spring", command.axis), effect)
            case SineCommand():
                self._sines.play(t, command)
            case PulseCommand():
                effect = pulse_effect(self._axes, command)
                self._pool("pulse", command.axis).play(t, effect, command.duration_s)
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
        effect = condition_effect(self._axes, command, self._length_us)
        key = (condition_kind(command), command.axis)
        if self._held.due(t, key, effect):
            self._held.play(t, key, effect)

    def _transient(self, t: float, command: TransientCommand) -> None:
        """A one-shot sine fading out over ``blend_out_s``, capped at its length."""
        period = period_us(command.frequency_hz)
        if period is None:
            log.debug("transient on %s with no frequency skipped", command.axis)
            return
        length = microseconds(command.duration_s)
        effect = sine_effect(
            self._axes,
            command.axis,
            period_us=period,
            magnitude=command.magnitude,
            length_us=length,
            phase=0,
            fade_us=min(microseconds(command.blend_out_s), length),
        )
        self._pool("transient", command.axis).play(t, effect, command.duration_s)

    def _pool(self, kind: str, axis: Axis) -> DInputPool:
        return self._pools.setdefault((kind, axis), DInputPool(self._channel))

    def _effect_ids(self) -> list[int]:
        pooled = [i for pool in self._pools.values() for i in pool.effect_ids]
        return self._held.effect_ids + pooled
