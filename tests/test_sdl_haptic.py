"""SDL haptic backend against the fake SDL: effect shapes and effect reuse."""

import pytest
from sdl_haptic_support import (
    PITCH_ONLY,
    STANDARD_AXES,
    effect_calls,
    last_effect,
    open_backend,
    steady_tick,
)
from sdl_support import FakeSdl, stick

from wardogs_flight_eng.engine.commands import (
    Axis,
    ConditionCommand,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
    PulseCommand,
    SineCommand,
    SpringCommand,
    TransientCommand,
)
from wardogs_flight_eng.outputs.protocol import ForceBackend
from wardogs_flight_eng.outputs.sdl_conditions import condition_effect


def test_refresh_every_tick_updates_in_place_and_reruns_every_tick() -> None:
    fake = FakeSdl(stick())
    backend: ForceBackend = open_backend(fake, refresh_every_tick=True)
    for n in range(100):
        backend.apply(n / 100, steady_tick())
    created = [i for i, _ in effect_calls(fake, "SDL_HapticNewEffect")]
    assert len(created) == 4
    updated = [i for i, _ in effect_calls(fake, "SDL_HapticUpdateEffect")]
    assert all(updated.count(effect_id) >= 99 for effect_id in created)
    assert fake.count("SDL_HapticRunEffect") == 400


def test_spring_condition_acts_on_its_axis_only() -> None:
    fake = FakeSdl(stick())
    open_backend(fake).apply(0.0, [SpringCommand(Axis.PITCH, 0.25, 0.35, 0.02)])
    spring = last_effect(fake, fake.SDL_HAPTIC_SPRING).condition
    assert spring.center == (0, 8192, 0)
    assert spring.right_coeff == spring.left_coeff == (0, 11468, 0)
    assert spring.deadband == (0, 655, 0)
    assert spring.right_sat == spring.left_sat == (0, 0xFFFF, 0)
    assert spring.direction.dir == PITCH_ONLY


@pytest.mark.parametrize(
    ("command", "kind", "coeff"),
    [
        (FrictionCommand(Axis.PITCH, 0.1), "SDL_HAPTIC_FRICTION", 3277),
        (DamperCommand(Axis.ROLL, 0.25), "SDL_HAPTIC_DAMPER", 8192),
        (InertiaCommand(Axis.PITCH, 0.08), "SDL_HAPTIC_INERTIA", 2621),
    ],
)
def test_condition_effect_shape(
    command: ConditionCommand, kind: str, coeff: int
) -> None:
    fake = FakeSdl(stick())
    effect = condition_effect(fake, STANDARD_AXES, command, 1000)
    assert effect.type == getattr(fake, kind)
    on = (0, coeff, 0) if command.axis is Axis.PITCH else (coeff, 0, 0)
    assert effect.condition.right_coeff == effect.condition.left_coeff == on
    assert effect.condition.center == effect.condition.deadband == (0, 0, 0)
    assert effect.condition.length == 1000


def test_sine_period_from_frequency() -> None:
    fake = FakeSdl(stick())
    open_backend(fake).apply(0.0, [SineCommand(Axis.ROLL, 5.5067, 0.4)])
    sine = last_effect(fake, fake.SDL_HAPTIC_SINE).periodic
    assert (sine.period, sine.magnitude) == (182, 13107)
    assert sine.direction.dir == (1, 0, 0)


def test_zero_frequency_silences_sine_and_keeps_period() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake)
    backend.apply(0.0, [SineCommand(Axis.PITCH, 6.0, 0.4)])
    backend.apply(0.01, [SineCommand(Axis.PITCH, 0.0, 0.4)])
    sine = last_effect(fake, fake.SDL_HAPTIC_SINE).periodic
    assert (sine.period, sine.magnitude) == (167, 0)


def test_refresh_every_tick_carries_sine_phase_tick_to_tick() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake, refresh_every_tick=True)
    backend.apply(0.0, [SineCommand(Axis.PITCH, 5.5067, 0.4)])
    assert last_effect(fake, fake.SDL_HAPTIC_SINE).periodic.phase == 0
    backend.apply(0.01, [SineCommand(Axis.PITCH, 5.5067, 0.4)])
    assert last_effect(fake, fake.SDL_HAPTIC_SINE).periodic.phase == 1978


def test_persistent_length_follows_setting() -> None:
    fake = FakeSdl(stick())
    open_backend(fake, length_s=0.5).apply(0.0, steady_tick())
    lengths = [
        e.condition.length if e.type == fake.SDL_HAPTIC_SPRING else e.periodic.length
        for _, e in effect_calls(fake, "SDL_HapticNewEffect")
    ]
    assert lengths == [500, 500, 500, 500]


def test_rejects_non_positive_persistent_length() -> None:
    with pytest.raises(ValueError, match="persistent_length_s"):
        open_backend(FakeSdl(stick()), length_s=0.0)


def test_pulse_creates_short_constant_effect() -> None:
    fake = FakeSdl(stick())
    open_backend(fake).apply(0.0, [PulseCommand(Axis.ROLL, -0.6, 0.02)])
    pulse = last_effect(fake, fake.SDL_HAPTIC_CONSTANT).constant
    assert (pulse.length, pulse.level) == (20, -19660)
    assert pulse.direction.dir == (1, 0, 0)
    assert fake.args("SDL_HapticRunEffect") == [(0, 1)]


def test_transient_is_fading_sine() -> None:
    fake = FakeSdl(stick())
    open_backend(fake).apply(0.0, [TransientCommand(Axis.PITCH, 6.0, 0.3, 0.4, 0.25)])
    shake = last_effect(fake, fake.SDL_HAPTIC_SINE).periodic
    assert (shake.length, shake.fade_length, shake.fade_level) == (400, 250, 0)
    assert (shake.period, shake.magnitude) == (167, 9830)


def test_transient_pool_wraps_to_oldest_slot() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake)
    for n in range(5):
        backend.apply(n * 0.04, [TransientCommand(Axis.PITCH, 6.0, 0.3, 0.4, 0.25)])
    created = [effect_id for effect_id, _ in effect_calls(fake, "SDL_HapticNewEffect")]
    assert created == [0, 1, 2, 3]
    assert fake.args("SDL_HapticStopEffect") == [(0,)]
    assert [i for i, _ in effect_calls(fake, "SDL_HapticUpdateEffect")] == [0]
    assert fake.names()[-3:] == [
        "SDL_HapticStopEffect",
        "SDL_HapticUpdateEffect",
        "SDL_HapticRunEffect",
    ]


def test_finished_pulse_slot_is_reused_without_stopping() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake)
    for n in range(25):
        backend.apply(n * 0.04, [PulseCommand(Axis.PITCH, 0.5, 0.02)])
    assert fake.count("SDL_HapticNewEffect") == 1
    assert fake.count("SDL_HapticUpdateEffect") == 24
    assert fake.count("SDL_HapticStopEffect") == 0
