"""Primitive probe for ``check-device --backend dinput8``.

Like the SDL probe it never starts an effect, so it produces no force: each
kind the base enumerates is created with zero coefficients and magnitude, and
the spring-centre update is a ``SetParameters`` (restart allowed) moving the
never-started spring's offset to 5000. A refused creation or update is a
``no``; a lost device raises ``DeviceLostError``. Every effect and the device
are released whatever happens; the DirectInput object stays with the caller.
"""

import logging
from dataclasses import dataclass
from functools import partial

from wardogs_flight_eng.engine.commands import (
    Axis,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
    PulseCommand,
    SpringCommand,
)
from wardogs_flight_eng.inputs.dinput_api import (
    DiAxisInfo,
    DiEffect,
    DInputError,
    DirectInputApi,
    EffectKind,
)
from wardogs_flight_eng.inputs.dinput_device import open_dinput_joystick
from wardogs_flight_eng.outputs.dinput_channel import (
    DInputChannel,
    ForceFailure,
    attempt,
)
from wardogs_flight_eng.outputs.dinput_effects import (
    condition_effect,
    microseconds,
    pulse_effect,
    sine_effect,
    spring_effect,
)
from wardogs_flight_eng.outputs.haptic_axes import HapticAxis, HapticAxisMap
from wardogs_flight_eng.outputs.sdl_probe import PrimitiveReport

__all__ = ["DInputProbeDetail", "PrimitiveReport", "probe_dinput"]

log = logging.getLogger(__name__)

_LENGTH_US = microseconds(1.0)
_PERIOD_US = microseconds(0.1)
_AXES = HapticAxisMap(pitch=HapticAxis(1, 1.0), roll=HapticAxis(0, 1.0))


@dataclass(frozen=True, slots=True)
class DInputProbeDetail:
    """The matched instance, its acquisition, read-back gain and axis objects.

    ``acquired`` is True once the open sequence's ``Acquire`` succeeded (a
    refused one raises before a detail exists); ``axes`` are the readable
    axis objects in index order.
    """

    instance_name: str
    acquired: bool
    ff_gain: int
    axes: list[DiAxisInfo]


def _spring(center: float) -> DiEffect:
    return spring_effect(_AXES, SpringCommand(Axis.PITCH, center, 0.0, 0.0), _LENGTH_US)


def _effects() -> dict[EffectKind, DiEffect]:
    """One zero-strength effect of every kind, on the pitch axis."""
    sine = sine_effect(
        _AXES,
        Axis.PITCH,
        period_us=_PERIOD_US,
        magnitude=0.0,
        length_us=_LENGTH_US,
        phase=0,
    )
    return {
        "spring": _spring(0.0),
        "sine": sine,
        "constant": pulse_effect(_AXES, PulseCommand(Axis.PITCH, 0.0, 0.1)),
        "friction": condition_effect(
            _AXES, FrictionCommand(Axis.PITCH, 0.0), _LENGTH_US
        ),
        "damper": condition_effect(_AXES, DamperCommand(Axis.PITCH, 0.0), _LENGTH_US),
        "inertia": condition_effect(_AXES, InertiaCommand(Axis.PITCH, 0.0), _LENGTH_US),
    }


def _create(channel: DInputChannel, effect: DiEffect) -> int | None:
    try:
        return channel.create(effect)
    except DInputError as err:
        log.info("%s effect rejected: %s", effect.kind, err)
        return None


def _moves(channel: DInputChannel, spring: int) -> bool:
    """True when DirectInput accepts the spring with its centre moved."""
    try:
        channel.update(spring, _spring(0.5), norestart=False)
    except DInputError as err:
        log.info("spring centre update rejected: %s", err)
        return False
    return True


def _probe(channel: DInputChannel, kinds: frozenset[EffectKind]) -> PrimitiveReport:
    created: dict[EffectKind, int] = {}
    try:
        for kind, effect in _effects().items():
            effect_id = _create(channel, effect) if kind in kinds else None
            if effect_id is not None:
                created[kind] = effect_id
        spring = created.get("spring")
        return PrimitiveReport(
            spring=spring is not None,
            spring_center_moves=spring is not None and _moves(channel, spring),
            sine="sine" in created,
            constant="constant" in created,
            friction="friction" in created,
            damper="damper" in created,
            inertia="inertia" in created,
        )
    finally:
        _release(channel, list(created.values()))


def _release(channel: DInputChannel, effect_ids: list[int]) -> None:
    """Release every effect, each attempted; the first failure is raised."""
    failures: list[ForceFailure] = []
    for effect_id in effect_ids:
        attempt(failures, partial(channel.release, effect_id))
    if failures:
        raise failures[0]


def probe_dinput(
    api: DirectInputApi, sdl_guid: str
) -> tuple[PrimitiveReport, DInputProbeDetail]:
    """Open the base matching ``sdl_guid`` and try each primitive."""
    joystick = open_dinput_joystick(api, sdl_guid)
    try:
        kinds = api.enum_effect_kinds(joystick.handle)
        report = _probe(DInputChannel(api, joystick.handle), kinds)
        detail = DInputProbeDetail(
            joystick.name,
            True,
            api.get_ff_gain(joystick.handle),
            list(joystick.axes_info),
        )
        return report, detail
    finally:
        joystick.close()
