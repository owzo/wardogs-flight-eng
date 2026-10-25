"""DirectInput effect builders: units, axis placement and silencing."""

import pytest

from wardogs_flight_eng.engine.commands import (
    Axis,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
    PulseCommand,
    SpringCommand,
)
from wardogs_flight_eng.inputs.dinput_api import DiEnvelope
from wardogs_flight_eng.outputs.dinput_effects import (
    condition_effect,
    di_phase,
    di_scale,
    microseconds,
    offset_for,
    period_us,
    pulse_effect,
    silenced,
    sine_effect,
    spring_effect,
)
from wardogs_flight_eng.outputs.haptic_axes import HapticAxis, HapticAxisMap

NORMAL = HapticAxisMap(HapticAxis(1, 1.0), HapticAxis(0, 1.0))
INVERTED = HapticAxisMap(HapticAxis(1, -1.0), HapticAxis(0, -1.0))


def test_di_scale_maps_to_ten_thousand_and_clamps() -> None:
    assert di_scale(0.35) == 3500
    assert di_scale(-0.6) == -6000
    assert di_scale(2.0) == 10000
    assert di_scale(-2.0) == -10000


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_di_scale_fails_closed_on_non_finite(bad: float) -> None:
    assert di_scale(bad) == 0


def test_microseconds_rounds_and_rejects_non_positive() -> None:
    assert microseconds(1.0) == 1_000_000
    assert microseconds(0.0004) == 400
    assert microseconds(-1.0) == 0
    assert microseconds(float("nan")) == 0


def test_period_us_inverts_frequency() -> None:
    assert period_us(5.5067) == 181_597
    assert period_us(1e9) == 1
    assert period_us(0.0) is None
    assert period_us(-3.0) is None
    assert period_us(float("nan")) is None


def test_di_phase_wraps_a_turn() -> None:
    assert di_phase(9000) == 9000
    assert di_phase(36000) == 0
    assert di_phase(-100) == 35900


def test_offset_for_follows_dijofs_order() -> None:
    assert [offset_for(HapticAxis(i, 1.0)) for i in range(3)] == [0, 4, 8]


def test_spring_acts_on_its_axis_with_centre_and_deadband() -> None:
    effect = spring_effect(NORMAL, SpringCommand(Axis.PITCH, 0.25, 0.35, 0.02), -1)
    assert effect.kind == "spring"
    assert effect.axes == (4,)
    assert effect.direction == (1,)
    assert effect.gain == 10000
    assert effect.duration_us == -1
    (condition,) = effect.condition
    assert condition.offset == 2500
    assert condition.positive_coefficient == condition.negative_coefficient == 3500
    assert condition.positive_saturation == condition.negative_saturation == 10000
    assert condition.dead_band == 200


def test_spring_centre_flips_on_an_inverted_axis() -> None:
    effect = spring_effect(INVERTED, SpringCommand(Axis.PITCH, 0.25, 0.1, -0.02), 0)
    (condition,) = effect.condition
    assert condition.offset == -2500
    assert condition.dead_band == 200
    assert effect.axes == (4,)


@pytest.mark.parametrize(
    ("command", "kind"),
    [
        (FrictionCommand(Axis.ROLL, 0.1), "friction"),
        (DamperCommand(Axis.ROLL, 0.1), "damper"),
        (InertiaCommand(Axis.ROLL, 0.1), "inertia"),
    ],
)
def test_condition_kind_follows_the_command_class(
    command: FrictionCommand | DamperCommand | InertiaCommand, kind: str
) -> None:
    effect = condition_effect(INVERTED, command, 0)
    assert effect.kind == kind
    assert effect.axes == (0,)
    (condition,) = effect.condition
    assert condition.positive_coefficient == condition.negative_coefficient == 1000
    assert condition.positive_saturation == condition.negative_saturation == 10000
    assert (condition.offset, condition.dead_band) == (0, 0)


def test_sine_carries_magnitude_phase_and_period() -> None:
    effect = sine_effect(
        NORMAL, Axis.ROLL, period_us=181_597, magnitude=0.4, length_us=-1, phase=9000
    )
    assert effect.kind == "sine"
    assert effect.axes == (0,)
    assert effect.direction == (1,)
    assert effect.periodic is not None
    assert effect.periodic.magnitude == 4000
    assert effect.periodic.offset == 0
    assert effect.periodic.phase == 9000
    assert effect.periodic.period_us == 181_597
    assert effect.envelope is None


def test_sine_fade_becomes_an_envelope() -> None:
    effect = sine_effect(
        NORMAL,
        Axis.PITCH,
        period_us=10_000,
        magnitude=0.4,
        length_us=250_000,
        phase=0,
        fade_us=100_000,
    )
    assert effect.duration_us == 250_000
    assert effect.envelope == DiEnvelope(10000, 0, 0, 100_000)


def test_pulse_level_carries_the_sign() -> None:
    effect = pulse_effect(NORMAL, PulseCommand(Axis.PITCH, -0.6, 0.25))
    assert effect.kind == "constant"
    assert effect.axes == (4,)
    assert effect.direction == (1,)
    assert effect.duration_us == 250_000
    assert effect.constant is not None
    assert effect.constant.magnitude == -6000


def test_pulse_level_flips_on_an_inverted_axis() -> None:
    effect = pulse_effect(INVERTED, PulseCommand(Axis.ROLL, -0.6, 0.25))
    assert effect.constant is not None
    assert effect.constant.magnitude == 6000


def test_silenced_zeroes_every_strength_and_keeps_the_payload() -> None:
    spring = silenced(
        spring_effect(NORMAL, SpringCommand(Axis.PITCH, 0.0, 0.5, 0.0), 0)
    )
    (condition,) = spring.condition
    assert condition.positive_coefficient == condition.negative_coefficient == 0
    sine = silenced(
        sine_effect(
            NORMAL, Axis.ROLL, period_us=1000, magnitude=0.4, length_us=0, phase=0
        )
    )
    assert sine.periodic is not None
    assert sine.periodic.magnitude == 0
    assert sine.periodic.period_us == 1000
    pulse = silenced(pulse_effect(NORMAL, PulseCommand(Axis.PITCH, 0.5, 0.1)))
    assert pulse.constant is not None
    assert pulse.constant.magnitude == 0
    assert pulse.duration_us == 100_000
