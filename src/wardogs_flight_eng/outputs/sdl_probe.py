"""Primitive probe for ``check-device``: can this base play what we need?

Effects are created (and the spring's centre moved) but never run, so the
probe produces no force; their axis placement is therefore irrelevant and a
fixed map (roll on haptic axis 0, pitch on 1) is used. A detached device
raises ``DeviceLostError``.
"""

import logging
from dataclasses import dataclass

from wardogs_flight_eng.engine.commands import (
    Axis,
    ConditionCommand,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
    PulseCommand,
    SpringCommand,
)
from wardogs_flight_eng.inputs.sdl_api import HapticEffect, SdlApi, SdlError
from wardogs_flight_eng.inputs.sdl_device import open_by_guid
from wardogs_flight_eng.outputs.haptic_axes import HapticAxis, HapticAxisMap
from wardogs_flight_eng.outputs.sdl_channel import HapticChannel
from wardogs_flight_eng.outputs.sdl_conditions import condition_effect, spring_effect
from wardogs_flight_eng.outputs.sdl_effects import pulse_effect, sine_effect

log = logging.getLogger(__name__)

_PROBE_LENGTH_MS = 1000
_PROBE_PERIOD_MS = 100
_PROBE_AXES = HapticAxisMap(pitch=HapticAxis(1, 1.0), roll=HapticAxis(0, 1.0))
_PROBE_CONDITIONS: tuple[ConditionCommand, ...] = (
    FrictionCommand(Axis.PITCH, 0.0),
    DamperCommand(Axis.PITCH, 0.0),
    InertiaCommand(Axis.PITCH, 0.0),
)


@dataclass(frozen=True, slots=True)
class PrimitiveReport:
    """Which effect primitives the device accepted.

    ``spring_center_moves`` means SDL accepted an update moving the spring's
    centre to 0.5; it is not a measured movement of the stick (the hardware
    conformance test measures that). ``friction``, ``damper`` and ``inertia``
    are the condition effects the feel model plays on top of the spring.
    """

    spring: bool
    spring_center_moves: bool
    sine: bool
    constant: bool
    friction: bool
    damper: bool
    inertia: bool


def probe_primitives(guid: str, api: SdlApi | None = None) -> PrimitiveReport:
    """Open the device ``guid`` and try each primitive; release everything."""
    device = open_by_guid(guid, api)
    try:
        channel = HapticChannel(device.api, device.joystick)
        try:
            return _probe(channel, device.api)
        finally:
            channel.close()
    finally:
        device.close()


def _probe(channel: HapticChannel, api: SdlApi) -> PrimitiveReport:
    supported = channel.query()
    created: list[int] = []

    def attempt(effect: HapticEffect) -> int | None:
        if not supported & effect.type:
            return None
        try:
            effect_id = channel.new(effect)
        except SdlError as err:
            log.info("effect type %d rejected: %s", effect.type, err)
            return None
        created.append(effect_id)
        return effect_id

    try:
        spring = attempt(_spring(api, 0.0))
        moves = spring is not None and _moves(channel, spring, _spring(api, 0.5))
        sine = attempt(
            sine_effect(
                api,
                _PROBE_AXES,
                Axis.PITCH,
                period=_PROBE_PERIOD_MS,
                magnitude=0.0,
                length_ms=_PROBE_LENGTH_MS,
            )
        )
        constant = attempt(
            pulse_effect(api, _PROBE_AXES, PulseCommand(Axis.PITCH, 0.0, 0.1))
        )
        friction, damper, inertia = (
            attempt(condition_effect(api, _PROBE_AXES, command, _PROBE_LENGTH_MS))
            is not None
            for command in _PROBE_CONDITIONS
        )
        return PrimitiveReport(
            spring is not None,
            moves,
            sine is not None,
            constant is not None,
            friction,
            damper,
            inertia,
        )
    finally:
        for effect_id in created:
            channel.destroy(effect_id)


def _spring(api: SdlApi, center: float) -> HapticEffect:
    command = SpringCommand(Axis.PITCH, center, 0.3, 0.0)
    return spring_effect(api, _PROBE_AXES, command, _PROBE_LENGTH_MS)


def _moves(channel: HapticChannel, effect_id: int, moved: HapticEffect) -> bool:
    """True when SDL accepts the spring with its centre moved."""
    try:
        channel.update(effect_id, moved)
    except SdlError as err:
        log.info("spring centre update rejected: %s", err)
        return False
    return True
