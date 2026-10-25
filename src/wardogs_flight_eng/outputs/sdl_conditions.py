"""Builders for the SDL condition effects: spring, friction, damper, inertia.

Each acts on one haptic axis only: the coefficients and saturation sit on that
axis's index and the other two are 0, and the direction is Cartesian along it.
A spring carries a centre and deadband from its command; friction, damper and
inertia are centred at 0 with no deadband, so only the coefficient varies.
"""

from typing import assert_never

from wardogs_flight_eng.engine.commands import (
    ConditionCommand,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
    SpringCommand,
)
from wardogs_flight_eng.inputs.sdl_api import HapticCondition, HapticEffect, SdlApi
from wardogs_flight_eng.outputs.haptic_axes import HapticAxisMap
from wardogs_flight_eng.outputs.sdl_effects import direction, on_axis, scale

SATURATION_MAX = 0xFFFF


def spring_effect(
    api: SdlApi, axes: HapticAxisMap, command: SpringCommand, length_ms: int
) -> HapticEffect:
    """Single-axis centring spring about ``command.center`` (frame space)."""
    axis = axes[command.axis]
    coefficient = on_axis(axis, scale(command.coefficient))
    condition = HapticCondition(
        direction=direction(api, axis),
        length=length_ms,
        right_sat=on_axis(axis, SATURATION_MAX),
        left_sat=on_axis(axis, SATURATION_MAX),
        right_coeff=coefficient,
        left_coeff=coefficient,
        deadband=on_axis(axis, scale(max(0.0, command.deadband))),
        center=on_axis(axis, scale(command.center * axis.sign)),
    )
    return HapticEffect(api.SDL_HAPTIC_SPRING, condition=condition)


def condition_effect(
    api: SdlApi, axes: HapticAxisMap, command: ConditionCommand, length_ms: int
) -> HapticEffect:
    """Single-axis friction, damper or inertia; the SDL type follows the class."""
    axis = axes[command.axis]
    coefficient = on_axis(axis, scale(command.coefficient))
    condition = HapticCondition(
        direction=direction(api, axis),
        length=length_ms,
        right_sat=on_axis(axis, SATURATION_MAX),
        left_sat=on_axis(axis, SATURATION_MAX),
        right_coeff=coefficient,
        left_coeff=coefficient,
    )
    return HapticEffect(condition_type(api, command), condition=condition)


def condition_type(api: SdlApi, command: ConditionCommand) -> int:
    """The SDL effect type for ``command``'s class."""
    match command:
        case FrictionCommand():
            return api.SDL_HAPTIC_FRICTION
        case DamperCommand():
            return api.SDL_HAPTIC_DAMPER
        case InertiaCommand():
            return api.SDL_HAPTIC_INERTIA
        case _:
            assert_never(command)
