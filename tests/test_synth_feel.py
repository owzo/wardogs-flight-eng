"""Feel conditions, the clamp blend and the airspeed estimate in the engine."""

import logging
import math

import pytest
from synth_support import PROFILES, engine_for, frame, pitch_friction, sine_magnitude

from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Axis,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
    SineCommand,
    SpringCommand,
)
from wardogs_flight_eng.engine.flight_state import FlightState
from wardogs_flight_eng.engine.frame import Button, ControlFrame
from wardogs_flight_eng.engine.profile import load_profile
from wardogs_flight_eng.engine.synth import FlightEngine


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
