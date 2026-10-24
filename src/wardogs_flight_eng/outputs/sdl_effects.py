"""Pure builders for the SDL haptic effects the force backend plays.

Normalised values scale to SDL's 16-bit range (x 32767, non-finite -> 0);
lengths and periods are milliseconds (periods and fades capped at SDL's
Uint16 65535), phase is hundredths of a degree. Commands arrive in frame
space; a ``HapticAxisMap`` places each on its device haptic axis and flips
the signed values (spring centre, pulse level) for an inverted binding.
Periodic and constant effects point along their haptic axis in Cartesian
coordinates; the condition effects (spring, friction, damper, inertia) are
built in ``sdl_conditions`` from ``on_axis`` and ``direction``.
"""

import math
from dataclasses import replace

from wardogs_flight_eng.engine.commands import (
    Axis,
    PulseCommand,
    TransientCommand,
)
from wardogs_flight_eng.inputs.sdl_api import (
    HapticConstant,
    HapticDirection,
    HapticEffect,
    HapticPeriodic,
    SdlApi,
    Triple,
)
from wardogs_flight_eng.outputs.haptic_axes import HapticAxis, HapticAxisMap

FULL_SCALE = 32767
PHASE_TURN = 36000
UINT16_MAX = 0xFFFF
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
    """``round(1000 / f)`` ms in 1..65535; None when ``f`` is not positive."""
    if not math.isfinite(frequency_hz) or frequency_hz <= 0:
        return None
    return max(1, min(UINT16_MAX, round(1000 / frequency_hz)))


def advance_phase(phase: int, elapsed_s: float, period: int) -> int:
    """Phase after ``elapsed_s`` of a sine with ``period`` ms, wrapped to a turn."""
    if not math.isfinite(elapsed_s) or elapsed_s <= 0:
        return phase
    return round(phase + PHASE_TURN * elapsed_s * 1000 / period) % PHASE_TURN


def on_axis(axis: HapticAxis, value: int) -> Triple:
    """``value`` on ``axis``'s haptic index, 0 on the other two."""
    values = [0, 0, 0]
    values[axis.haptic_index] = value
    return (values[0], values[1], values[2])


def direction(api: SdlApi, axis: HapticAxis) -> HapticDirection:
    """Cartesian unit direction along ``axis``."""
    return HapticDirection(api.SDL_HAPTIC_CARTESIAN, on_axis(axis, 1))


def sine_effect(
    api: SdlApi,
    axes: HapticAxisMap,
    axis: Axis,
    *,
    period: int,
    magnitude: float,
    length_ms: int,
    phase: int = 0,
    fade_length: int = 0,
) -> HapticEffect:
    """Unsigned sine along ``axis``; ``fade_length`` fades it out at the end."""
    periodic = HapticPeriodic(
        direction=direction(api, axes[axis]),
        length=length_ms,
        period=period,
        magnitude=scale(magnitude),
        phase=phase,
        fade_length=min(UINT16_MAX, fade_length),
        fade_level=0,
    )
    return HapticEffect(api.SDL_HAPTIC_SINE, periodic=periodic)


def pulse_effect(
    api: SdlApi, axes: HapticAxisMap, command: PulseCommand
) -> HapticEffect:
    """Constant push; the sign of ``level`` is the device-space direction."""
    axis = axes[command.axis]
    constant = HapticConstant(
        direction=direction(api, axis),
        length=milliseconds(command.duration_s),
        level=scale(command.magnitude * axis.sign),
    )
    return HapticEffect(api.SDL_HAPTIC_CONSTANT, constant=constant)


def transient_effect(
    api: SdlApi, axes: HapticAxisMap, command: TransientCommand, period: int
) -> HapticEffect:
    """One-shot sine faded to zero over the last ``blend_out_s``."""
    return sine_effect(
        api,
        axes,
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
