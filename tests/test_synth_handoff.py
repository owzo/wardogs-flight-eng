"""Profile handoff: ``take_over`` is the only way to carry state over."""

import pytest
from profile_support import raw_profile
from synth_support import engine_for, frame, pitch_friction

from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Axis,
    Command,
    PulseCommand,
    SineCommand,
    SpringCommand,
)
from wardogs_flight_eng.engine.frame import Button
from wardogs_flight_eng.engine.profile import Profile
from wardogs_flight_eng.engine.synth import FlightEngine


def hold_engine(name: str) -> FlightEngine:
    raw = raw_profile(name)
    raw["feel"]["trim_style"] = "hold"
    return FlightEngine(Profile.from_document(raw), load_constants())


def pitch_spring(cmds: list[Command]) -> SpringCommand:
    return next(
        c for c in cmds if isinstance(c, SpringCommand) and c.axis is Axis.PITCH
    )


def test_engine_has_no_public_latch_setter_or_prime() -> None:
    assert not hasattr(FlightEngine, "prime_buttons")
    assert isinstance(FlightEngine.all_off, property)
    assert FlightEngine.all_off.fset is None


def test_profile_and_latch_carried_into_a_handoff() -> None:
    lb, lak = engine_for("littlebird-miniguns"), engine_for("lakota")
    assert lak.profile.name == "lakota"
    lb.step(0.01, frame(0, 0, 0, 0, Button.ALL_OFF))
    lb.step(0.01, frame())
    lak.take_over(lb)
    assert lak.all_off is True
    assert lak.step(0.01, frame()) == [AllOffCommand()]
    lak.step(0.01, frame(0, 0, 0, 0, Button.ALL_OFF))  # tapped again: released
    assert lak.all_off is False
    assert lak.step(0.01, frame()) != [AllOffCommand()]


def test_take_over_resets_feel_and_airspeed_and_carries_the_rotor() -> None:
    lb, lak = engine_for("littlebird-miniguns"), engine_for("lakota")
    lb.step(0.01, frame(1.0, 0, 1.0, 0, Button.TRIM_LOCK))
    for _ in range(300):  # 3 s: the Littlebird spools fully
        lb.step(0.01, frame(1.0, 0, 1.0, 0))
    lak.take_over(lb)
    cmds = lak.step(0.01, frame())
    spring = next(
        c for c in cmds if isinstance(c, SpringCommand) and c.axis is Axis.PITCH
    )
    sine = next(c for c in cmds if isinstance(c, SineCommand))
    assert spring.center == 0.0 and lak.state.airspeed == 0.0
    assert sine.frequency_hz == pytest.approx(250 / 60, rel=0.01)  # Lakota rpm


def test_take_over_resets_a_locked_force_trim_anchor() -> None:
    first, second = engine_for("lakota"), engine_for("havoc")
    second.step(0.01, frame(0.5, 0.5, 0, 0, Button.TRIM_LOCK))
    for _ in range(50):
        second.step(0.01, frame(0.5, 0.5))
    first.take_over(second)
    second.take_over(first)
    cmds = second.step(0.01, frame(0.5, 0.5))
    assert all(c.center == 0.0 for c in cmds if isinstance(c, SpringCommand))


def test_take_over_from_itself_keeps_a_locked_anchor() -> None:
    lak = engine_for("lakota")
    lak.step(0.01, frame(0.5, 0.5, 0, 0, Button.TRIM_LOCK))
    for _ in range(50):
        before = lak.step(0.01, frame(0.5, 0.5))
    lak.take_over(lak)
    after = lak.step(0.01, frame(0.5, 0.5))
    centers = [c.center for c in before if isinstance(c, SpringCommand)]
    assert centers and all(c != 0.0 for c in centers)
    assert [c.center for c in after if isinstance(c, SpringCommand)] == centers


def test_take_over_carries_the_latch_and_held_buttons() -> None:
    lb, lak = engine_for("littlebird-miniguns"), engine_for("lakota")
    lb.step(0.01, frame(0, 0, 0, 0, Button.ALL_OFF))
    lak.take_over(lb)
    assert lak.all_off is True
    assert lak.step(0.01, frame(0, 0, 0, 0, Button.ALL_OFF)) == [AllOffCommand()]
    assert lak.all_off is True  # still held across the handoff: no toggle


def test_take_over_gives_a_fresh_weapon() -> None:
    lb, other = engine_for("littlebird-miniguns"), engine_for("lakota")
    firing = frame(0, 0, 0.5, 0, Button.FIRE)
    for _ in range(30):  # past the 0.25 s wind-up: firing every 0.04 s
        lb.step(0.01, firing)
    lb.take_over(other)
    for _ in range(20):  # 0.2 s: inside a fresh wind-up, so no round yet
        cmds = lb.step(0.01, firing)
        assert not any(isinstance(c, PulseCommand) for c in cmds)


def test_cycling_back_to_a_clamped_engine_starts_it_free() -> None:
    lb, lak = engine_for("littlebird-miniguns"), engine_for("lakota")
    lb.step(0.01, frame(0, 0, 0, 0, Button.TRIM_LOCK))
    for _ in range(40):
        clamped = lb.step(0.01, frame())
    assert pitch_friction(clamped) == 0.5
    lak.take_over(lb)
    lb.take_over(lak)
    assert pitch_friction(lb.step(0.01, frame())) == 0.02


def test_held_trim_lock_across_handoff_is_blocked_until_released() -> None:
    hold_lak, lb = hold_engine("lakota"), engine_for("littlebird-miniguns")
    lb.step(0.01, frame(0, 0, 0, 0, Button.TRIM_LOCK))
    hold_lak.take_over(lb)
    for _ in range(40):
        cmds = hold_lak.step(0.01, frame(0, 0, 0, 0, Button.TRIM_LOCK))
    assert pitch_spring(cmds).coefficient == 0.5  # still stiff: blocked
    hold_lak.step(0.01, frame())  # released once
    for _ in range(40):
        cmds = hold_lak.step(0.01, frame(0, 0, 0, 0, Button.TRIM_LOCK))
    assert pitch_spring(cmds).coefficient == 0.0  # now it slackens


def test_hold_style_unboosted_engine_clamps_only_while_held() -> None:
    lb = hold_engine("littlebird-miniguns")
    held = frame(0, 0, 0, 0, Button.TRIM_LOCK)
    for _ in range(40):
        cmds = lb.step(0.01, held)
    assert pitch_friction(cmds) == 0.5
    cmds = lb.step(0.01, frame(0, 0, 0, 0, Button.TRIM_LOCK, Button.TRIM_RESET))
    assert pitch_friction(cmds) == 0.5  # reset is a no-op in hold style
    for _ in range(40):
        cmds = lb.step(0.01, frame())
    assert pitch_friction(cmds) == 0.02


def test_hold_style_force_trim_release_places_the_anchor_at_the_stick() -> None:
    lak = hold_engine("lakota")
    for _ in range(40):
        cmds = lak.step(0.01, frame(0, 0, 0, 0, Button.TRIM_LOCK))
    assert pitch_spring(cmds).coefficient == 0.0
    cmds = lak.step(0.01, frame(0.4, -0.2))  # released here
    assert pitch_spring(cmds).center == 0.4  # placed on the release tick
    assert pitch_spring(cmds).coefficient < 0.5
    for _ in range(40):
        cmds = lak.step(0.01, frame(0.4, -0.2))
    assert (pitch_spring(cmds).center, pitch_spring(cmds).coefficient) == (0.4, 0.5)
