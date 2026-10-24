import logging
import math

import pytest

from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Axis,
    Command,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
    PulseCommand,
    SineCommand,
    SpringCommand,
    TransientCommand,
)
from wardogs_flight_eng.engine.flight_state import FlightState
from wardogs_flight_eng.engine.frame import Button, ControlFrame
from wardogs_flight_eng.engine.profile import PROFILES_DIR, ProfileError, load_profile
from wardogs_flight_eng.engine.synth import FlightEngine

PROFILES = PROFILES_DIR


def engine_for(name: str) -> FlightEngine:
    return FlightEngine(load_profile(PROFILES / f"{name}.json"), load_constants())


def frame(
    pitch: float = 0,
    roll: float = 0,
    collective: float = 0,
    pedals: float = 0,
    *held: Button,
) -> ControlFrame:
    return ControlFrame(pitch, roll, collective, pedals, frozenset(held))


def test_idle_tick_emits_centered_springs_and_silent_buzz() -> None:
    e = engine_for("littlebird-miniguns")
    cmds = e.step(0.01, frame())
    springs = [c for c in cmds if isinstance(c, SpringCommand)]
    assert {s.axis for s in springs} == {Axis.PITCH, Axis.ROLL} and all(
        s.center == 0 for s in springs
    )
    assert {s.axis: s.coefficient for s in springs} == {
        Axis.PITCH: 0.12,
        Axis.ROLL: pytest.approx(0.06),
    }  # roll_scale 0.5
    assert all(
        c.magnitude == 0 for c in cmds if isinstance(c, SineCommand)
    )  # collective 0


def test_trim_lock_tap_moves_spring_center_once() -> None:
    e = engine_for("lakota")  # force_trim: the Littlebird clamps instead
    e.step(0.01, frame(0.4, -0.2, 0.5, 0, Button.TRIM_LOCK))
    for _ in range(100):
        cmds = e.step(
            0.01, frame(0.4, -0.2, 0.5, 0, Button.TRIM_LOCK)
        )  # still held: no re-lock
    centers = {c.axis: c.center for c in cmds if isinstance(c, SpringCommand)}
    assert centers == {Axis.PITCH: pytest.approx(0.4), Axis.ROLL: pytest.approx(-0.2)}


def test_buzz_frequency_is_airframe_one_per_rev() -> None:
    e = engine_for("havoc")
    for _ in range(400):
        cmds = e.step(0.01, frame(collective=1.0))
    # brief used a set of pytest.approx (unhashable); a list pins both axes
    assert [c.frequency_hz for c in cmds if isinstance(c, SineCommand)] == [
        pytest.approx(4.5)
    ] * 2


def test_fire_yields_pulses_on_both_axes_after_windup() -> None:
    e = engine_for("littlebird-miniguns")
    for _ in range(30):
        e.step(0.01, frame(0, 0, 0.5, 0, Button.FIRE))
    cmds = e.step(0.04, frame(0, 0, 0.5, 0, Button.FIRE))
    pulses = [c for c in cmds if isinstance(c, PulseCommand)]
    assert len(pulses) == 2 and {p.axis for p in pulses} == {Axis.PITCH, Axis.ROLL}
    assert pulses[0].duration_s == pytest.approx(0.02)


def test_watchdog_dt_emits_all_off_not_pulses() -> None:  # Review Focus 5
    e = engine_for("littlebird-miniguns")
    for _ in range(30):
        e.step(0.01, frame(0, 0, 1, 0, Button.FIRE))
    assert e.step(0.5, frame(0, 0, 1, 0, Button.FIRE)) == [AllOffCommand()]


def test_all_off_latches_until_tapped_again() -> None:
    e = engine_for("lakota")
    assert e.step(0.01, frame(0, 0, 0, 0, Button.ALL_OFF)) == [AllOffCommand()]
    assert e.step(0.01, frame()) == [AllOffCommand()]
    e.step(0.01, frame(0, 0, 0, 0, Button.ALL_OFF))
    assert any(isinstance(c, SpringCommand) for c in e.step(0.01, frame()))


def test_havoc_has_no_recoil() -> None:
    e = engine_for("havoc")
    for _ in range(300):
        cmds = e.step(0.01, frame(0, 0, 1, 0, Button.FIRE))
    assert not any(isinstance(c, PulseCommand) for c in cmds)


def test_rockets_emit_transient_shake_per_round() -> None:
    e = engine_for("littlebird-rockets")
    # 350 rpm: rounds at t = 0 and 60/350 = 0.171 s (Task 6 timing: first round
    # the instant firing starts), so 2 rounds in 0.2 s -> 2 shakes per axis.
    # The brief's "1 round in 0.2 s" / len == 2 contradicted that convention.
    cmds = e.step(0.2, frame(0, 0, 0.5, 0, Button.FIRE))
    shakes = [c for c in cmds if isinstance(c, TransientCommand)]
    assert [c.axis for c in shakes] == [Axis.PITCH, Axis.ROLL] * 2
    assert (
        len(shakes) == 4
        and shakes[0].frequency_hz == 6
        and shakes[0].duration_s == 0.4
        and shakes[0].magnitude == 0.3
    )


def test_rotor_toggle_tap_spools_down() -> None:
    e = engine_for("littlebird-miniguns")
    for _ in range(400):
        e.step(0.01, frame(collective=1.0))
    e.step(0.01, frame(0, 0, 1, 0, Button.ROTOR_TOGGLE))
    for _ in range(100):
        cmds = e.step(0.01, frame(collective=1.0))  # 1 s at 850 rpm/s: 330.4 → 0
    assert {c.frequency_hz for c in cmds if isinstance(c, SineCommand)} == {0.0}
    assert all(c.magnitude == 0 for c in cmds if isinstance(c, SineCommand))


# --- beyond the brief: semantics the brief states but does not pin ---------
def test_all_off_property_tracks_the_latch() -> None:
    e = engine_for("lakota")
    assert e.all_off is False
    e.step(0.01, frame(0, 0, 0, 0, Button.ALL_OFF))
    assert e.all_off is True
    e.step(0.01, frame(0, 0, 0, 0, Button.ALL_OFF))  # still held: no toggle
    assert e.all_off is True
    e.step(0.01, frame())
    e.step(0.01, frame(0, 0, 0, 0, Button.ALL_OFF))
    assert e.all_off is False


def test_watchdog_tick_freezes_state_and_does_not_latch() -> None:
    e = engine_for("lakota")  # force_trim, trim_slew_s 0.3
    e.step(0.01, frame(0.6, 0, 0, 0, Button.TRIM_LOCK))
    assert e.step(10.0, frame(0.6, 0, 0, 0, Button.TRIM_LOCK)) == [AllOffCommand()]
    assert e.all_off is False
    cmds = e.step(0.01, frame(0.6, 0, 0, 0, Button.TRIM_LOCK))
    pitch = [c.center for c in cmds if isinstance(c, SpringCommand)][0]
    assert pitch == pytest.approx(0.6 * 0.02 / 0.3)  # only 0.02 s of slew elapsed


def test_trim_reset_tap_returns_center_to_origin() -> None:
    e = engine_for("lakota")
    e.step(0.01, frame(0.5, 0.5, 0, 0, Button.TRIM_LOCK))
    for _ in range(50):  # first tick is the reset tap; 0.5 s > trim_slew_s 0.3
        cmds = e.step(0.01, frame(0.5, 0.5, 0, 0, Button.TRIM_RESET))
    assert all(c.center == 0 for c in cmds if isinstance(c, SpringCommand))


def test_cyclic_deflection_from_trim_raises_buzz() -> None:
    centred, deflected = engine_for("havoc"), engine_for("havoc")
    for _ in range(400):
        quiet = centred.step(0.01, frame(collective=1.0))
        # |d| = 1.0; aft cyclic, so the airspeed estimate stays 0
        loud = deflected.step(0.01, frame(-0.6, 0.8, 1.0, 0))
    base = [c.magnitude for c in quiet if isinstance(c, SineCommand)]
    boosted = [c.magnitude for c in loud if isinstance(c, SineCommand)]
    assert base == [pytest.approx(0.35)] * 2  # base x full spool x collective 1
    assert boosted == [pytest.approx(0.35 * 1.5)] * 2  # deflection_factor 0.5


def test_each_tick_has_conditions_then_sines_in_axis_order() -> None:
    cmds = engine_for("lakota").step(0.01, frame())
    kinds = [(type(c), c.axis) for c in cmds if not isinstance(c, AllOffCommand)]
    kinds_in_order = (
        SpringCommand,
        FrictionCommand,
        DamperCommand,
        InertiaCommand,
        SineCommand,
    )
    assert kinds == [(k, a) for k in kinds_in_order for a in (Axis.PITCH, Axis.ROLL)]


def test_rocket_pulse_kicks_rearward_on_pitch() -> None:
    e = engine_for("lakota")
    cmds = e.step(0.01, frame(0, 0, 0.5, 0, Button.FIRE))
    pulses = {c.axis: c for c in cmds if isinstance(c, PulseCommand)}
    assert pulses[Axis.PITCH].magnitude == pytest.approx(-0.6)
    assert pulses[Axis.ROLL].magnitude == 0
    assert pulses[Axis.PITCH].duration_s == pytest.approx(0.5 / (500 / 60))


def test_reload_tap_silences_fire() -> None:
    e = engine_for("lakota")
    for _ in range(100):  # first tick is the tap; 1 s < the 7 s reload
        cmds = e.step(0.01, frame(0, 0, 0.5, 0, Button.FIRE, Button.RELOAD))
        assert not any(isinstance(c, PulseCommand) for c in cmds)


def test_engine_rejects_profile_unknown_to_constants() -> None:
    p = load_profile(PROFILES / "lakota.json").model_copy(update={"airframe": "x"})
    with pytest.raises(ProfileError, match="'x'"):
        FlightEngine(p, load_constants())


def test_profile_and_all_off_setter_for_profile_handoff() -> None:
    e = engine_for("lakota")
    assert e.profile.name == "lakota"
    e.all_off = True
    assert e.step(0.01, frame()) == [AllOffCommand()]
    e.all_off = False
    assert e.step(0.01, frame()) != [AllOffCommand()]


def test_primed_buttons_are_not_taps() -> None:
    e = engine_for("lakota")
    e.all_off = True
    e.prime_buttons(frozenset({Button.ALL_OFF}))
    assert e.step(0.01, frame(0, 0, 0, 0, Button.ALL_OFF)) == [AllOffCommand()]
    assert e.all_off is True  # held across the handoff: no toggle


@pytest.mark.parametrize("bad_dt", [float("nan"), float("inf"), -0.01])
def test_non_finite_or_negative_dt_fails_closed_and_freezes_state(
    bad_dt: float,
) -> None:
    held = frame(0.6, 0.4, 1.0, 0, Button.TRIM_LOCK)
    gated, reference = (
        engine_for("littlebird-miniguns"),
        engine_for("littlebird-miniguns"),
    )
    for e in (gated, reference):
        e.step(0.01, held)  # trim lock tap; trim slewing, rotor spooling up
    assert gated.step(bad_dt, held) == [AllOffCommand()]
    assert gated.all_off is False
    after, expected = gated.step(0.01, held), reference.step(0.01, held)
    assert after[:8] == expected[:8]  # every feel condition, the clamp blend too
    sines = [(c.frequency_hz, c.magnitude) for c in after if isinstance(c, SineCommand)]
    assert sines == [
        (c.frequency_hz, c.magnitude) for c in expected if isinstance(c, SineCommand)
    ]
    assert all(f > 0 for f, _ in sines)  # the rotor really was spooling


def test_spool_down_placeholder_is_logged_once_for_an_airframe_without_one(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="wardogs_flight_eng.engine.builders"):
        engine_for("lakota")
    notes = [r.getMessage() for r in caplog.records if "spool-down" in r.getMessage()]
    assert len(notes) == 1
    assert "lakota" in notes[0] and "the Littlebird's game value" in notes[0]
    assert "not this airframe's" in notes[0]


def test_spool_down_placeholder_not_logged_for_the_littlebird(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="wardogs_flight_eng.engine.builders"):
        engine_for("littlebird-miniguns")
    assert not [r for r in caplog.records if "spool-down" in r.getMessage()]


# --- feel conditions, the airspeed estimate and the profile handoff ----------
def pitch_friction(cmds: list[Command]) -> float:
    return next(
        c.coefficient
        for c in cmds
        if isinstance(c, FrictionCommand) and c.axis is Axis.PITCH
    )


def sine_magnitude(cmds: list[Command]) -> float:
    return next(c.magnitude for c in cmds if isinstance(c, SineCommand))


def test_idle_tick_emits_all_four_conditions_per_axis() -> None:
    cmds = engine_for("lakota").step(0.01, frame())
    assert [type(c) for c in cmds[:8]] == [SpringCommand] * 2 + [
        FrictionCommand
    ] * 2 + [DamperCommand] * 2 + [InertiaCommand] * 2


def test_littlebird_lock_clamps_instead_of_moving_the_centre() -> None:
    e = engine_for("littlebird-miniguns")
    e.step(0.01, frame(0.4, 0.0, 0.5, 0, Button.TRIM_LOCK))
    for _ in range(40):
        cmds = e.step(0.01, frame(0.4, 0.0, 0.5, 0))
    spring = next(
        c for c in cmds if isinstance(c, SpringCommand) and c.axis is Axis.PITCH
    )
    assert (spring.center, spring.coefficient, pitch_friction(cmds)) == (
        0.0,
        0.0,
        0.5,
    )


def test_buzz_grows_with_sustained_forward_stick() -> None:
    e = engine_for("littlebird-miniguns")
    early = e.step(0.01, frame(pitch=0.6, collective=1.0))
    for _ in range(2000):
        late = e.step(0.01, frame(pitch=0.6, collective=1.0))
    assert sine_magnitude(late) > 1.2 * sine_magnitude(early)
    assert e.state.airspeed == pytest.approx((0.6 - 0.15) / 0.85, abs=0.01)


def test_state_before_the_first_step_is_at_rest() -> None:
    assert engine_for("lakota").state == FlightState(0.0, 0.0, 0.0)


def test_stub_estimator_is_used_when_given() -> None:
    class Fast:
        def step(
            self, dt: float, frame: ControlFrame, deflection: float
        ) -> FlightState:
            return FlightState(1.0, frame.collective, deflection)

        def restart(self) -> None:
            pass

    profile = load_profile(PROFILES / "lakota.json")
    e = FlightEngine(profile, load_constants(), estimator=Fast())
    for _ in range(400):
        cmds = e.step(0.01, frame(collective=1.0))
    assert sine_magnitude(cmds) == pytest.approx(0.3 * 1.15)


def test_watchdog_tick_advances_neither_blend_nor_airspeed() -> None:
    e = engine_for("littlebird-miniguns")  # trim_slew_s 0.3, tau_s 4.0
    # blend 1/30, airspeed 1 - e^-0.0025
    e.step(0.01, frame(1.0, 0, 0.5, 0, Button.TRIM_LOCK))
    assert e.step(5.0, frame(1.0)) == [AllOffCommand()]
    assert e.state.airspeed == pytest.approx(1 - math.exp(-0.0025), abs=1e-5)
    cmds = e.step(0.01, frame(1.0))  # blend 2/30 now, not more
    assert pitch_friction(cmds) == pytest.approx(0.02 + 0.48 * 2 / 30, abs=1e-3)


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
