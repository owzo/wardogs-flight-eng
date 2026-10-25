"""Pure builders for the DirectInput effects the force backend plays.

Normalised values scale to DirectInput's ``DI_FFNOMINALMAX`` range (x 10000,
non-finite -> 0); lengths and periods are microseconds, phase is hundredths
of a degree. Commands arrive in frame space; a ``HapticAxisMap`` places each
on its device axis (a ``DIJOFS_*`` offset) and flips the signed values
(spring centre, pulse level) for an inverted binding. Every effect acts on
one axis with the Cartesian direction ``(1,)``, so a pulse carries its push
direction in the sign of its constant magnitude.
"""

import math
from dataclasses import replace
from typing import assert_never

from wardogs_flight_eng.engine.commands import (
    Axis,
    ConditionCommand,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
    PulseCommand,
    SpringCommand,
)
from wardogs_flight_eng.inputs.dinput_api import (
    DIJOFS_BY_INDEX,
    DiCondition,
    DiConstant,
    DiEffect,
    DiEnvelope,
    DiPeriodic,
    EffectKind,
)
from wardogs_flight_eng.outputs.haptic_axes import HapticAxis, HapticAxisMap

FULL_SCALE = 10000
PHASE_TURN = 36000
_CARTESIAN_UNIT = (1,)


def di_scale(value: float) -> int:
    """Map -1..1 to -10000..10000 (clamped); NaN or infinity fails closed to 0."""
    if not math.isfinite(value):
        return 0
    return round(max(-1.0, min(1.0, value)) * FULL_SCALE)


def microseconds(seconds: float) -> int:
    """Seconds to whole microseconds, rounded; non-positive or non-finite -> 0."""
    if not math.isfinite(seconds) or seconds <= 0:
        return 0
    return round(seconds * 1_000_000)


def period_us(frequency_hz: float) -> int | None:
    """``round(1e6 / f)`` µs, at least 1; None when ``f`` is not positive."""
    if not math.isfinite(frequency_hz) or frequency_hz <= 0:
        return None
    return max(1, round(1_000_000 / frequency_hz))


def di_phase(phase_turn: int) -> int:
    """Phase in hundredths of a degree, wrapped to 0..35999."""
    return phase_turn % PHASE_TURN


def offset_for(axis: HapticAxis) -> int:
    """The ``DIJOFS_*`` offset of ``axis``'s haptic index."""
    return DIJOFS_BY_INDEX[axis.haptic_index]


def _condition(
    kind: EffectKind,
    axis: HapticAxis,
    length_us: int,
    coefficient: float,
    *,
    center: int = 0,
    dead_band: int = 0,
) -> DiEffect:
    strength = di_scale(coefficient)
    condition = DiCondition(
        offset=center,
        positive_coefficient=strength,
        negative_coefficient=strength,
        positive_saturation=FULL_SCALE,
        negative_saturation=FULL_SCALE,
        dead_band=dead_band,
    )
    return DiEffect(
        kind,
        axes=(offset_for(axis),),
        direction=_CARTESIAN_UNIT,
        duration_us=length_us,
        gain=FULL_SCALE,
        condition=(condition,),
    )


def spring_effect(
    axes: HapticAxisMap, command: SpringCommand, length_us: int
) -> DiEffect:
    """Single-axis centring spring about ``command.center`` (frame space)."""
    axis = axes[command.axis]
    return _condition(
        "spring",
        axis,
        length_us,
        command.coefficient,
        center=di_scale(command.center * axis.sign),
        dead_band=di_scale(abs(command.deadband)),
    )


def condition_effect(
    axes: HapticAxisMap, command: ConditionCommand, length_us: int
) -> DiEffect:
    """Single-axis friction, damper or inertia; the kind follows the class."""
    return _condition(
        condition_kind(command), axes[command.axis], length_us, command.coefficient
    )


def condition_kind(command: ConditionCommand) -> EffectKind:
    """The DirectInput effect kind for ``command``'s class."""
    match command:
        case FrictionCommand():
            return "friction"
        case DamperCommand():
            return "damper"
        case InertiaCommand():
            return "inertia"
        case _:
            assert_never(command)


def sine_effect(
    axes: HapticAxisMap,
    axis: Axis,
    *,
    period_us: int,
    magnitude: float,
    length_us: int,
    phase: int,
    fade_us: int = 0,
) -> DiEffect:
    """Unsigned sine along ``axis``; ``fade_us`` fades it out at the end."""
    envelope = DiEnvelope(FULL_SCALE, 0, 0, fade_us) if fade_us > 0 else None
    return DiEffect(
        "sine",
        axes=(offset_for(axes[axis]),),
        direction=_CARTESIAN_UNIT,
        duration_us=length_us,
        gain=FULL_SCALE,
        periodic=DiPeriodic(di_scale(magnitude), 0, di_phase(phase), period_us),
        envelope=envelope,
    )


def pulse_effect(axes: HapticAxisMap, command: PulseCommand) -> DiEffect:
    """Constant push; the sign of the magnitude is the device-space direction."""
    axis = axes[command.axis]
    return DiEffect(
        "constant",
        axes=(offset_for(axis),),
        direction=_CARTESIAN_UNIT,
        duration_us=microseconds(command.duration_s),
        gain=FULL_SCALE,
        constant=DiConstant(di_scale(command.magnitude * axis.sign)),
    )


def silenced(effect: DiEffect) -> DiEffect:
    """``effect`` with zero coefficients, sine magnitude and constant level."""
    return replace(
        effect,
        condition=tuple(
            replace(c, positive_coefficient=0, negative_coefficient=0)
            for c in effect.condition
        ),
        periodic=None
        if effect.periodic is None
        else replace(effect.periodic, magnitude=0),
        constant=None
        if effect.constant is None
        else replace(effect.constant, magnitude=0),
    )
