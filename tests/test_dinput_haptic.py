"""DirectInput haptic backend against the fake: effect shapes, pools, conditions."""

import logging

import pytest
from dinput_haptic_support import (
    PITCH_OFFSET,
    ROLL_OFFSET,
    SINE_5_5,
    SINE_6,
    STANDARD_AXES,
    created,
    fresh,
    last_effect,
    steady_tick,
    updates,
)
from dinput_support import ab9

from wardogs_flight_eng.engine.commands import (
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
from wardogs_flight_eng.inputs.dinput_api import (
    DiCondition,
    DiConstant,
    DiEffect,
    DiEnvelope,
    DiPeriodic,
    EffectKind,
)
from wardogs_flight_eng.outputs.haptic_axes import HapticAxis, HapticAxisMap

INVERTED = HapticAxisMap(pitch=HapticAxis(1, -1.0), roll=HapticAxis(0, 1.0))


def _held(kind: EffectKind, offset: int, condition: DiCondition) -> DiEffect:
    return DiEffect(kind, (offset,), (1,), 1_000_000, 10000, (condition,))


@pytest.mark.parametrize(("axes", "center"), [(STANDARD_AXES, 2500), (INVERTED, -2500)])
def test_spring_acts_on_its_axis_with_the_binding_sign(
    axes: HapticAxisMap, center: int
) -> None:
    fake, backend = fresh(axis_map=axes)
    backend.apply(0.0, [SpringCommand(Axis.PITCH, 0.25, 0.35, 0.02)])
    spring = DiCondition(center, 3500, 3500, 10000, 10000, 200)
    assert last_effect(fake, "spring") == _held("spring", PITCH_OFFSET, spring)
    assert fake.names() == ["create_effect", "start"]


def test_sine_period_and_magnitude_from_the_command() -> None:
    fake, backend = fresh()
    backend.apply(0.0, [SineCommand(Axis.ROLL, 5.5067, 0.4)])
    sine = last_effect(fake, "sine")
    assert sine.periodic == DiPeriodic(4000, 0, 0, SINE_5_5)
    assert (sine.axes, sine.duration_us, sine.envelope) == ((ROLL_OFFSET,), 10**6, None)


def test_zero_frequency_silences_sine_and_keeps_period() -> None:
    fake, backend = fresh()
    backend.apply(0.0, [SineCommand(Axis.PITCH, 6.0, 0.4)])
    backend.apply(0.01, [SineCommand(Axis.PITCH, 0.0, 0.4)])
    sine = last_effect(fake, "sine").periodic
    assert sine is not None and (sine.period_us, sine.magnitude) == (SINE_6, 0)


def test_persistent_length_follows_setting() -> None:
    fake, backend = fresh(length_s=0.5)
    backend.apply(0.0, steady_tick())
    assert [e.duration_us for _, e in created(fake)] == [500_000] * 4


@pytest.mark.parametrize("length_s", [0.0, -1.0, float("nan"), float("inf")])
def test_rejects_invalid_persistent_length(length_s: float) -> None:
    with pytest.raises(ValueError, match="persistent_length_s"):
        fresh(length_s=length_s)


def test_pulse_creates_short_constant_effect() -> None:
    fake, backend = fresh()
    backend.apply(0.0, [PulseCommand(Axis.ROLL, -0.6, 0.02)])
    pulse = last_effect(fake, "constant")
    assert (pulse.constant, pulse.duration_us) == (DiConstant(-6000), 20_000)
    assert pulse.axes == (ROLL_OFFSET,)
    assert fake.args("start") == [(0,)]


@pytest.mark.parametrize(
    ("duration_s", "length_us", "fade_us"),
    [(0.4, 400_000, 250_000), (0.1, 100_000, 100_000)],  # the fade never outlasts it
)
def test_transient_is_a_fading_sine(
    duration_s: float, length_us: int, fade_us: int
) -> None:
    fake, backend = fresh()
    backend.apply(0.0, [TransientCommand(Axis.PITCH, 6.0, 0.3, duration_s, 0.25)])
    shake = last_effect(fake, "sine")
    assert (shake.duration_us, shake.envelope) == (
        length_us,
        DiEnvelope(10000, 0, 0, fade_us),
    )
    assert (shake.periodic, shake.axes) == (DiPeriodic(3000, 0, 0, SINE_6), (4,))


def test_transient_without_frequency_is_skipped() -> None:
    fake, backend = fresh()
    backend.apply(0.0, [TransientCommand(Axis.ROLL, 0.0, 0.3, 0.4, 0.25)])
    assert fake.calls == []


def test_transient_pool_wraps_to_oldest_slot() -> None:
    fake, backend = fresh()
    for n in range(5):
        backend.apply(n * 0.04, [TransientCommand(Axis.PITCH, 6.0, 0.3, 0.4, 0.25)])
    assert [effect_id for effect_id, _ in created(fake)] == [0, 1, 2, 3]
    assert fake.args("stop") == [(0,)]
    assert [(i, norestart) for i, _, norestart in updates(fake)] == [(0, False)]
    assert fake.names()[-3:] == ["stop", "set_parameters", "start"]


def test_finished_pulse_slot_is_reused_without_stopping() -> None:
    fake, backend = fresh()
    for n in range(25):
        backend.apply(n * 0.04, [PulseCommand(Axis.PITCH, 0.5, 0.02)])
    assert (fake.count("create_effect"), fake.count("set_parameters")) == (1, 24)
    assert fake.count("stop") == 0


@pytest.mark.parametrize(
    ("command", "kind", "coeff", "offset"),
    [
        (FrictionCommand(Axis.PITCH, 0.1), "friction", 1000, PITCH_OFFSET),
        (DamperCommand(Axis.ROLL, 0.25), "damper", 2500, ROLL_OFFSET),
        (InertiaCommand(Axis.PITCH, 0.08), "inertia", 800, PITCH_OFFSET),
    ],
)
def test_condition_effect_shape(
    command: ConditionCommand, kind: EffectKind, coeff: int, offset: int
) -> None:
    fake, backend = fresh()
    backend.apply(0.0, [command])
    condition = DiCondition(0, coeff, coeff, 10000, 10000, 0)
    assert last_effect(fake, kind) == _held(kind, offset, condition)


def test_conditions_are_persistent_and_updated_only_on_change() -> None:
    fake, backend = fresh()
    tick: list[Command] = [
        FrictionCommand(Axis.PITCH, 0.02),
        DamperCommand(Axis.PITCH, 0.15),
        InertiaCommand(Axis.PITCH, 0.05),
    ]
    for n in range(50):
        backend.apply(n / 100, tick)
    assert (len(created(fake)), fake.count("set_parameters")) == (3, 0)
    backend.apply(0.5, [FrictionCommand(Axis.PITCH, 0.5)])
    assert [(i, norestart) for i, _, norestart in updates(fake)] == [(0, True)]
    assert last_effect(fake, "friction").condition[0].positive_coefficient == 5000


def test_unsupported_condition_is_dropped_after_one_warning_at_open(
    caplog: pytest.LogCaptureFixture,
) -> None:
    device = ab9()
    device.kinds = frozenset({"constant", "sine", "spring", "friction"})
    with caplog.at_level(logging.WARNING):
        fake, backend = fresh(device=device)
    assert backend.missing_conditions == frozenset({"damper", "inertia"})
    assert sum("damper" in r.message for r in caplog.records) == 1
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        tick = (DamperCommand(Axis.ROLL, 0.3), FrictionCommand(Axis.ROLL, 0.1))
        for n in range(10):
            backend.apply(n / 100, tick)
    assert not caplog.records
    assert [e.kind for _, e in created(fake)] == ["friction"]


def test_empty_effect_list_disables_every_condition_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    device = ab9()
    device.kinds = frozenset()
    with caplog.at_level(logging.WARNING):
        fake, backend = fresh(device=device)
        backend.apply(0.0, [FrictionCommand(Axis.PITCH, 0.1)])
    assert backend.missing_conditions == frozenset({"friction", "damper", "inertia"})
    assert sum("did not report" in r.message for r in caplog.records) == 1
    assert fake.calls == []
