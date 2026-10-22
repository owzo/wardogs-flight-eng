"""Pure builders for the SDL haptic effects the force backend plays.

Normalised values scale to SDL's 16-bit range (x 32767, non-finite -> 0);
lengths and periods are milliseconds, phase is hundredths of a degree. Each
effect acts on one stick axis: roll is haptic axis 0 (X), pitch is haptic
axis 1 (Y); a spring's other-axis coefficients are 0, and periodic and
constant effects point along their axis in Cartesian coordinates.
"""

import math
from dataclasses import replace

from wardogs_flight_eng.engine.commands import (
    Axis,
    PulseCommand,
    SpringCommand,
    TransientCommand,
)
from wardogs_flight_eng.inputs.sdl_api import (
    HapticCondition,
    HapticConstant,
    HapticDirection,
    HapticEffect,
    HapticPeriodic,
    SdlApi,
    Triple,
)

FULL_SCALE = 32767
SATURATION_MAX = 0xFFFF
PHASE_TURN = 36000
_AXIS_INDEX = {Axis.ROLL: 0, Axis.PITCH: 1}
_ZERO: Triple = (0, 0, 0)


def scale(value: float) -> int:
    """Map -1..1 to -32767..32767 (clamped); NaN or infinity fails closed to 0."""
    if not math.isfinite(value):
        return 0
    return round(max(-1.0, min(1.0, value)) * FULL_SCALE)


def milliseconds(seconds: float) -> int:
    """Seconds to whole milliseconds, rounded; non-positive or non-finite -> 0."""
    if not math.isfinite(seconds) or seconds <= 0:
        return 0
    return round(seconds * 1000)


def period_ms(frequency_hz: float) -> int | None:
    """``round(1000 / f)`` ms (at least 1); None when ``f`` is not positive."""
    if not math.isfinite(frequency_hz) or frequency_hz <= 0:
        return None
    return max(1, round(1000 / frequency_hz))


def advance_phase(phase: int, elapsed_s: float, period: int) -> int:
    """Phase after ``elapsed_s`` of a sine with ``period`` ms, wrapped to a turn."""
    if not math.isfinite(elapsed_s) or elapsed_s <= 0:
        return phase
    return round(phase + PHASE_TURN * elapsed_s * 1000 / period) % PHASE_TURN


def _on_axis(axis: Axis, value: int) -> Triple:
    values = [0, 0, 0]
    values[_AXIS_INDEX[axis]] = value
    return (values[0], values[1], values[2])


def _direction(api: SdlApi, axis: Axis) -> HapticDirection:
    return HapticDirection(api.SDL_HAPTIC_CARTESIAN, _on_axis(axis, 1))


def spring_effect(api: SdlApi, command: SpringCommand, length_ms: int) -> HapticEffect:
    """Single-axis centring spring about ``command.center``."""
    axis = command.axis
    coefficient = _on_axis(axis, scale(command.coefficient))
    condition = HapticCondition(
        direction=_direction(api, axis),
        length=length_ms,
        right_sat=_on_axis(axis, SATURATION_MAX),
        left_sat=_on_axis(axis, SATURATION_MAX),
        right_coeff=coefficient,
        left_coeff=coefficient,
        deadband=_on_axis(axis, scale(max(0.0, command.deadband))),
        center=_on_axis(axis, scale(command.center)),
    )
    return HapticEffect(api.SDL_HAPTIC_SPRING, condition=condition)


def sine_effect(
    api: SdlApi,
    axis: Axis,
    *,
    period: int,
    magnitude: float,
    length_ms: int,
    phase: int = 0,
    fade_length: int = 0,
) -> HapticEffect:
    """Sine along ``axis``; a ``fade_length`` fades it to zero at the end."""
    periodic = HapticPeriodic(
        direction=_direction(api, axis),
        length=length_ms,
        period=period,
        magnitude=scale(magnitude),
        phase=phase,
        fade_length=fade_length,
        fade_level=0,
    )
    return HapticEffect(api.SDL_HAPTIC_SINE, periodic=periodic)


def pulse_effect(api: SdlApi, command: PulseCommand) -> HapticEffect:
    """Constant push; the sign of ``level`` is the push direction."""
    constant = HapticConstant(
        direction=_direction(api, command.axis),
        length=milliseconds(command.duration_s),
        level=scale(command.magnitude),
    )
    return HapticEffect(api.SDL_HAPTIC_CONSTANT, constant=constant)


def transient_effect(
    api: SdlApi, command: TransientCommand, period: int
) -> HapticEffect:
    """One-shot sine faded to zero over the last ``blend_out_s``."""
    return sine_effect(
        api,
        command.axis,
        period=period,
        magnitude=command.magnitude,
        length_ms=milliseconds(command.duration_s),
        fade_length=milliseconds(command.blend_out_s),
    )


def silenced(effect: HapticEffect) -> HapticEffect:
    """``effect`` with zero spring coefficients, sine magnitude and level."""
    return replace(
        effect,
        condition=replace(effect.condition, right_coeff=_ZERO, left_coeff=_ZERO),
        periodic=replace(effect.periodic, magnitude=0),
        constant=replace(effect.constant, level=0),
    )
