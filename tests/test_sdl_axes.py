"""Frame-space -> device-space axis mapping and Uint16 limits in the haptic layer."""

import pytest
from sdl_haptic_support import last_effect, open_backend
from sdl_support import FakeSdl, stick

from wardogs_flight_eng.engine.commands import (
    Axis,
    PulseCommand,
    SineCommand,
    SpringCommand,
    TransientCommand,
)
from wardogs_flight_eng.engine.device_map import AxisBinding
from wardogs_flight_eng.outputs.haptic_axes import HapticAxis, HapticAxisMap


def _axes(
    pitch_axis: int = 1,
    roll_axis: int = 0,
    *,
    pitch_invert: bool = False,
    roll_invert: bool = False,
) -> HapticAxisMap:
    return HapticAxisMap.from_bindings(
        pitch=AxisBinding(device="stick", axis=pitch_axis, invert=pitch_invert),
        roll=AxisBinding(device="stick", axis=roll_axis, invert=roll_invert),
    )


def test_from_bindings_takes_index_and_sign() -> None:
    axes = _axes(pitch_invert=True)
    assert axes[Axis.PITCH] == HapticAxis(haptic_index=1, sign=-1.0)
    assert axes[Axis.ROLL] == HapticAxis(haptic_index=0, sign=1.0)


@pytest.mark.parametrize(
    ("pitch", "roll"),
    [
        (HapticAxis(1, 1.0), HapticAxis(1, 1.0)),
        (HapticAxis(3, 1.0), HapticAxis(0, 1.0)),
        (HapticAxis(1, 0.5), HapticAxis(0, 1.0)),
    ],
)
def test_rejects_unusable_maps(pitch: HapticAxis, roll: HapticAxis) -> None:
    with pytest.raises(ValueError, match="haptic"):
        HapticAxisMap(pitch=pitch, roll=roll)


def test_inverted_pitch_flips_spring_center_on_mapped_index() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake, axis_map=_axes(pitch_invert=True))
    backend.apply(0.0, [SpringCommand(Axis.PITCH, 0.3, 0.35, 0.02)])
    spring = last_effect(fake, fake.SDL_HAPTIC_SPRING).condition
    assert spring.center == (0, round(-0.3 * 32767), 0)
    assert spring.right_coeff == (0, 11468, 0)


def test_inverted_pitch_flips_pulse_level() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake, axis_map=_axes(pitch_invert=True))
    backend.apply(0.0, [PulseCommand(Axis.PITCH, 0.5, 0.02)])
    pulse = last_effect(fake, fake.SDL_HAPTIC_CONSTANT).constant
    assert pulse.level == round(-0.5 * 32767)
    assert pulse.direction.dir == (0, 1, 0)


def test_inverted_axis_leaves_sine_magnitude_unsigned() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake, axis_map=_axes(pitch_invert=True))
    backend.apply(0.0, [SineCommand(Axis.PITCH, 6.0, 0.4)])
    assert last_effect(fake, fake.SDL_HAPTIC_SINE).periodic.magnitude == 13107


def test_swapped_indices_swap_directions() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake, axis_map=_axes(pitch_axis=0, roll_axis=1))
    backend.apply(0.0, [PulseCommand(Axis.ROLL, 0.5, 0.02)])
    assert last_effect(fake, fake.SDL_HAPTIC_CONSTANT).constant.direction.dir == (
        0,
        1,
        0,
    )
    backend.apply(0.01, [SpringCommand(Axis.PITCH, 0.2, 0.3, 0.0)])
    spring = last_effect(fake, fake.SDL_HAPTIC_SPRING).condition
    assert spring.direction.dir == (1, 0, 0)
    assert spring.center == (6553, 0, 0)


def test_very_low_frequency_clamps_period_to_uint16() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake)
    backend.apply(0.0, [SineCommand(Axis.ROLL, 0.01, 0.4)])
    assert last_effect(fake, fake.SDL_HAPTIC_SINE).periodic.period == 65535


def test_long_transient_clamps_period_and_fade_to_uint16() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake)
    backend.apply(0.0, [TransientCommand(Axis.ROLL, 0.01, 0.3, 120.0, 100.0)])
    shake = last_effect(fake, fake.SDL_HAPTIC_SINE).periodic
    assert (shake.period, shake.fade_length, shake.length) == (65535, 65535, 120000)
