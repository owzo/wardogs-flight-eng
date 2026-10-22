import pytest

from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Axis,
    PulseCommand,
    SineCommand,
    SpringCommand,
    TransientCommand,
)
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
        Axis.PITCH: 0.35,
        Axis.ROLL: pytest.approx(0.175),
    }  # roll_scale 0.5
    assert all(
        c.magnitude == 0 for c in cmds if isinstance(c, SineCommand)
    )  # collective 0


def test_trim_lock_tap_moves_spring_center_once() -> None:
    e = engine_for("littlebird-miniguns")
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
    e = engine_for("littlebird-miniguns")  # trim_slew_s 0.3
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
        loud = deflected.step(0.01, frame(0.6, 0.8, 1.0, 0))  # |d| = 1.0
    base = [c.magnitude for c in quiet if isinstance(c, SineCommand)]
    boosted = [c.magnitude for c in loud if isinstance(c, SineCommand)]
    assert base == [pytest.approx(0.35)] * 2  # base x full spool x collective 1
    assert boosted == [pytest.approx(0.35 * 1.5)] * 2  # deflection_factor 0.5


def test_each_tick_has_springs_then_sines_in_axis_order() -> None:
    cmds = engine_for("lakota").step(0.01, frame())
    kinds = [(type(c), c.axis) for c in cmds if not isinstance(c, AllOffCommand)]
    pitch, roll = Axis.PITCH, Axis.ROLL
    spring, sine = SpringCommand, SineCommand
    assert kinds == [(spring, pitch), (spring, roll), (sine, pitch), (sine, roll)]


def test_rocket_pulse_kicks_rearward_on_pitch() -> None:
    e = engine_for("lakota")
    cmds = e.step(0.01, frame(0, 0, 0.5, 0, Button.FIRE))
    pulses = {c.axis: c for c in cmds if isinstance(c, PulseCommand)}
    assert pulses[Axis.PITCH].magnitude == pytest.approx(-0.8)
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
