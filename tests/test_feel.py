"""Feel model: force-trim anchor or unboosted clamp, four conditions per axis."""

import pytest

from wardogs_flight_eng.engine.commands import (
    Axis,
    Command,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
    SpringCommand,
)
from wardogs_flight_eng.engine.feel import FeelModel
from wardogs_flight_eng.engine.profile import PROFILES_DIR, load_profile

LB = load_profile(PROFILES_DIR / "littlebird-miniguns.json").feel  # unboosted
LAK = load_profile(PROFILES_DIR / "lakota.json").feel  # force_trim


def by_kind(cmds: list[Command], kind: type, axis: Axis) -> float:
    (c,) = [c for c in cmds if isinstance(c, kind) and c.axis is axis]
    return c.coefficient


def test_force_trim_emits_constant_conditions_and_moves_the_anchor() -> None:
    f = FeelModel(LAK)
    f.lock(0.4, -0.2)
    f.step(1.0)
    cmds = f.conditions()
    springs = [c for c in cmds if isinstance(c, SpringCommand)]
    assert [(s.axis, s.center, s.coefficient) for s in springs] == [
        (Axis.PITCH, pytest.approx(0.4), 0.5),
        (Axis.ROLL, pytest.approx(-0.2), 0.25),
    ]
    assert by_kind(cmds, FrictionCommand, Axis.PITCH) == 0.1
    assert by_kind(cmds, FrictionCommand, Axis.ROLL) == pytest.approx(0.05)
    assert (
        by_kind(cmds, DamperCommand, Axis.ROLL)
        == 0.25
        == by_kind(cmds, DamperCommand, Axis.PITCH)
    )
    assert by_kind(cmds, InertiaCommand, Axis.ROLL) == 0.08
    assert [type(c) for c in cmds] == [SpringCommand] * 2 + [FrictionCommand] * 2 + [
        DamperCommand
    ] * 2 + [InertiaCommand] * 2


def test_unboosted_free_is_weak_spring_about_centre_with_light_friction() -> None:
    f = FeelModel(LB)
    f.step(0.01)
    cmds = f.conditions()
    pitch_spring = next(
        c for c in cmds if isinstance(c, SpringCommand) and c.axis is Axis.PITCH
    )
    assert (pitch_spring.center, pitch_spring.coefficient) == (0.0, 0.12)
    assert by_kind(cmds, FrictionCommand, Axis.PITCH) == 0.02


def test_unboosted_lock_clamps_over_the_slew_and_never_moves_the_centre() -> None:
    f = FeelModel(LB)  # trim_slew_s 0.3
    f.lock(0.6, 0.1)
    f.step(0.15)
    assert f.clamp_blend == pytest.approx(0.5)
    half = f.conditions()
    assert by_kind(half, SpringCommand, Axis.PITCH) == pytest.approx(0.06)
    assert by_kind(half, FrictionCommand, Axis.PITCH) == pytest.approx(0.26)
    f.step(0.15)
    done = f.conditions()
    assert by_kind(done, SpringCommand, Axis.PITCH) == 0.0
    assert by_kind(done, FrictionCommand, Axis.PITCH) == 0.5
    assert by_kind(done, FrictionCommand, Axis.ROLL) == 0.25
    assert (f.center_pitch, f.center_roll) == (0.0, 0.0)


def test_lock_while_clamped_and_reset_while_free_are_no_ops() -> None:
    f = FeelModel(LB)
    f.reset()
    f.step(0.01)
    assert f.clamp_blend == 0.0
    f.lock(0.5, 0.0)
    f.step(1.0)
    f.lock(-0.5, 0.0)
    f.step(0.01)
    assert f.clamp_blend == 1.0


def test_reset_mid_blend_turns_back_from_current_value() -> None:  # Review Focus 1
    f = FeelModel(LB)
    f.lock(0.5, 0.0)
    f.step(0.15)
    f.reset()
    f.step(0.075)
    assert f.clamp_blend == pytest.approx(0.25)


def test_zero_slew_snaps_the_clamp() -> None:  # Review Focus 2
    f = FeelModel(LB.model_copy(update={"trim_slew_s": 0.0}))
    f.lock(0.0, 0.0)
    f.step(0.0)
    assert f.clamp_blend == 1.0


def test_restart_frees_and_centres_immediately() -> None:
    f = FeelModel(LAK)
    f.lock(0.4, 0.4)
    f.step(1.0)
    f.restart()
    assert (f.center_pitch, f.center_roll) == (0.0, 0.0)
    g = FeelModel(LB)
    g.lock(0.0, 0.0)
    g.step(1.0)
    g.restart()
    assert g.clamp_blend == 0.0
