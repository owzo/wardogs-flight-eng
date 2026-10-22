"""The real-SDL adapter builds genuine pysdl2 effect structs from the mirror.

Only struct conversion is exercised (no ``SDL_Init``, no device), so this runs
wherever ``sdl2`` imports; it is skipped where it does not.
"""

import importlib
import warnings
from dataclasses import fields
from types import ModuleType

import pytest

from wardogs_flight_eng.engine.commands import Axis, PulseCommand, SpringCommand
from wardogs_flight_eng.inputs.sdl_api import (
    HapticCondition,
    HapticConstant,
    HapticPeriodic,
)
from wardogs_flight_eng.inputs.sdl_real import RealSdl, to_sdl_effect
from wardogs_flight_eng.outputs.sdl_effects import (
    pulse_effect,
    sine_effect,
    spring_effect,
)


@pytest.fixture(scope="module")
def sdl2() -> ModuleType:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return importlib.import_module("sdl2")
        except ImportError as err:
            pytest.skip(f"sdl2 unavailable: {err}")


def test_mirror_fields_exist_in_pysdl2_structs(sdl2: ModuleType) -> None:
    pairs = [
        (HapticCondition, sdl2.SDL_HapticCondition),
        (HapticPeriodic, sdl2.SDL_HapticPeriodic),
        (HapticConstant, sdl2.SDL_HapticConstant),
    ]
    for mirror, struct in pairs:
        real = {name for name, *_ in struct._fields_}
        assert {f.name for f in fields(mirror)} <= real, mirror.__name__


def test_spring_converts_to_condition_struct(sdl2: ModuleType) -> None:
    api = RealSdl(sdl2)
    mirror = spring_effect(api, SpringCommand(Axis.PITCH, 0.25, 0.35, 0.02), 1000)
    out = to_sdl_effect(sdl2, mirror)
    assert isinstance(out, sdl2.SDL_HapticEffect)
    assert out.type == sdl2.SDL_HAPTIC_SPRING
    assert out.condition.type == sdl2.SDL_HAPTIC_SPRING
    assert list(out.condition.center) == [0, 8192, 0]
    assert list(out.condition.right_coeff) == [0, 11468, 0]
    assert list(out.condition.right_sat) == [0, 0xFFFF, 0]
    assert out.condition.length == 1000
    assert out.condition.direction.type == sdl2.SDL_HAPTIC_CARTESIAN
    assert list(out.condition.direction.dir) == [0, 1, 0]


def test_sine_and_constant_convert(sdl2: ModuleType) -> None:
    api = RealSdl(sdl2)
    sine = sine_effect(
        api, Axis.ROLL, period=182, magnitude=0.4, length_ms=400, fade_length=250
    )
    periodic = to_sdl_effect(sdl2, sine).periodic
    assert (periodic.period, periodic.magnitude) == (182, 13107)
    assert (periodic.length, periodic.fade_length) == (400, 250)
    pulse = pulse_effect(api, PulseCommand(Axis.ROLL, -0.6, 0.02))
    constant = to_sdl_effect(sdl2, pulse).constant
    assert (constant.level, constant.length) == (-19660, 20)
    assert list(constant.direction.dir) == [1, 0, 0]
