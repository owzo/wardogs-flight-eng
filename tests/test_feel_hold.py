"""Hold-to-release trim: slack spring (force_trim) or momentary clamp (unboosted)."""

import pytest

from wardogs_flight_eng.engine.commands import Axis, Command, SpringCommand
from wardogs_flight_eng.engine.feel import FeelModel
from wardogs_flight_eng.engine.profile import PROFILES_DIR, load_profile

LB = load_profile(PROFILES_DIR / "littlebird-miniguns.json").feel  # unboosted
LAK = load_profile(PROFILES_DIR / "lakota.json").feel  # force_trim
HOLD_FT = LAK.model_copy(update={"trim_style": "hold"})  # slew 0.3, spring 0.5
HOLD_UB = LB.model_copy(update={"trim_style": "hold"})


def pitch_spring(cmds: list[Command]) -> float:
    (c,) = [c for c in cmds if isinstance(c, SpringCommand) and c.axis is Axis.PITCH]
    return c.coefficient


def test_force_trim_hold_slackens_the_spring_without_moving_the_anchor() -> None:
    f = FeelModel(HOLD_FT)
    f.hold(True, 0.4, 0.0)
    f.step(0.15)
    assert pitch_spring(f.conditions()) == pytest.approx(0.25)
    assert f.center_pitch == 0.0
    f.step(0.15)
    assert pitch_spring(f.conditions()) == 0.0


def test_force_trim_release_anchors_at_the_stick_and_restiffens() -> None:
    f = FeelModel(HOLD_FT)
    f.hold(True, 0.0, 0.0)
    f.step(0.3)
    f.hold(False, 0.4, -0.2)
    f.step(0.3)
    springs = [c for c in f.conditions() if isinstance(c, SpringCommand)]
    assert [s.center for s in springs] == pytest.approx([0.4, -0.2])
    assert [s.coefficient for s in springs] == [0.5, 0.25]


def test_release_mid_slew_continues_from_the_current_fraction() -> None:
    f = FeelModel(HOLD_FT)
    f.hold(True, 0.0, 0.0)
    f.step(0.15)  # slack 0.5
    f.hold(False, 0.0, 0.0)
    f.step(0.075)  # back to 0.25
    assert f.slack == pytest.approx(0.25)


def test_holding_released_does_not_re_anchor() -> None:
    f = FeelModel(HOLD_FT)
    f.hold(False, 0.4, -0.2)
    f.step(0.3)
    assert (f.center_pitch, f.center_roll) == (0.0, 0.0)


def test_force_trim_hold_reset_still_recentres() -> None:
    f = FeelModel(HOLD_FT)
    f.hold(True, 0.0, 0.0)
    f.hold(False, 0.4, -0.2)
    f.step(0.3)
    f.reset()
    f.step(0.3)
    assert (f.center_pitch, f.center_roll) == (0.0, 0.0)


def test_unboosted_hold_is_a_momentary_clamp_and_reset_is_a_no_op() -> None:
    f = FeelModel(HOLD_UB)
    f.hold(True, 0.0, 0.0)
    f.step(0.3)
    assert f.clamp_blend == 1.0
    assert f.slack == 0.0
    f.reset()
    f.step(0.01)
    assert f.clamp_blend == 1.0
    f.hold(False, 0.0, 0.0)
    f.step(0.3)
    assert f.clamp_blend == 0.0


def test_restart_clears_a_held_slack() -> None:
    f = FeelModel(HOLD_FT)
    f.hold(True, 0.0, 0.0)
    f.step(0.3)
    f.restart()
    assert f.slack == 0.0 and pitch_spring(f.conditions()) == 0.5


def test_restart_forgets_the_held_state_so_a_release_does_not_anchor() -> None:
    f = FeelModel(HOLD_FT)
    f.hold(True, 0.0, 0.0)
    f.restart()
    f.hold(False, 0.4, -0.2)
    f.step(0.3)
    assert (f.center_pitch, f.center_roll) == (0.0, 0.0)
