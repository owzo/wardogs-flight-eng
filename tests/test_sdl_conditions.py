"""SDL haptic backend: condition effects and device capability gating."""

import logging

import pytest
from sdl_haptic_support import (
    PITCH_ONLY,
    STANDARD_AXES,
    destroyed_ids,
    effect_calls,
    last_effect,
    open_backend,
)
from sdl_support import FakeSdl, stick

from wardogs_flight_eng.engine.commands import (
    Axis,
    Command,
    ConditionCommand,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
    SpringCommand,
)
from wardogs_flight_eng.outputs.sdl_conditions import condition_effect


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


def test_conditions_are_persistent_and_updated_only_on_change() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake)
    tick: list[Command] = [
        FrictionCommand(Axis.PITCH, 0.02),
        DamperCommand(Axis.PITCH, 0.15),
        InertiaCommand(Axis.PITCH, 0.05),
    ]
    for n in range(50):
        backend.apply(n / 100, tick)
    assert len(effect_calls(fake, "SDL_HapticNewEffect")) == 3
    assert fake.count("SDL_HapticUpdateEffect") == 0
    backend.apply(0.5, [FrictionCommand(Axis.PITCH, 0.5)])
    assert fake.count("SDL_HapticUpdateEffect") == 1
    friction = last_effect(fake, fake.SDL_HAPTIC_FRICTION).condition
    assert friction.right_coeff == (0, 16384, 0)


def test_unsupported_condition_is_dropped_with_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeSdl(
        stick(),
        supported=FakeSdl.SDL_HAPTIC_CONSTANT
        | FakeSdl.SDL_HAPTIC_SINE
        | FakeSdl.SDL_HAPTIC_SPRING
        | FakeSdl.SDL_HAPTIC_FRICTION,
    )
    backend = open_backend(fake)
    with caplog.at_level(logging.WARNING):
        for n in range(10):
            backend.apply(
                n / 100,
                [DamperCommand(Axis.ROLL, 0.3), FrictionCommand(Axis.ROLL, 0.1)],
            )
    assert backend.missing_conditions == frozenset({"damper", "inertia"})
    assert len([r for r in caplog.records if "damper" in r.message]) == 1
    assert all(e.type != fake.SDL_HAPTIC_DAMPER for e in fake.effects.values())
    assert any(e.type == fake.SDL_HAPTIC_FRICTION for e in fake.effects.values())


def test_zero_capability_mask_disables_every_condition_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeSdl(stick())
    fake.query_result = 0
    with caplog.at_level(logging.WARNING):
        backend = open_backend(fake)
        backend.apply(
            0.0,
            [
                SpringCommand(Axis.PITCH, 0.0, 0.3, 0.0),
                FrictionCommand(Axis.PITCH, 0.1),
            ],
        )
    assert backend.missing_conditions == frozenset({"friction", "damper", "inertia"})
    assert sum("did not report" in r.message for r in caplog.records) == 1
    assert [e.type for e in fake.effects.values()] == [fake.SDL_HAPTIC_SPRING]


def test_all_off_silences_conditions_and_close_destroys_them() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake)
    backend.apply(
        0.0, [FrictionCommand(Axis.PITCH, 0.3), InertiaCommand(Axis.ROLL, 0.1)]
    )
    backend.all_off()
    assert all(e.condition.right_coeff == (0, 0, 0) for e in fake.effects.values())
    backend.close()
    assert len(destroyed_ids(fake)) == 2
