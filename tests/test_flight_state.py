import math

import pytest

from wardogs_flight_eng.engine.flight_state import FlightState, InputEstimator
from wardogs_flight_eng.engine.frame import ControlFrame


def frame(pitch: float = 0, collective: float = 0) -> ControlFrame:
    return ControlFrame(pitch, 0, collective, 0, frozenset())


def _est() -> InputEstimator:
    return InputEstimator(forward_threshold=0.15, tau_s=4.0)


def test_full_forward_reaches_63_percent_at_tau() -> None:
    e = _est()
    for _ in range(400):
        state = e.step(0.01, frame(pitch=1.0), 0.0)
    assert state.airspeed == pytest.approx(1 - math.exp(-1), abs=1e-3)


def test_partial_forward_targets_the_scaled_value() -> None:
    e = InputEstimator(0.15, 0.0)  # tau 0 snaps
    assert e.step(0.01, frame(pitch=0.5), 0.0).airspeed == pytest.approx(0.35 / 0.85)


def test_aft_stick_snaps_to_zero_with_tau_zero() -> None:
    e = InputEstimator(0.15, 0.0)
    e.step(0.01, frame(pitch=1.0), 0.0)
    assert e.step(0.01, frame(pitch=0.1), 0.0).airspeed == 0.0
    e.step(0.01, frame(pitch=1.0), 0.0)
    assert e.step(0.01, frame(pitch=-1.0), 0.0).airspeed == 0.0


def test_pitch_at_threshold_targets_zero() -> None:
    e = InputEstimator(0.15, 0.0)
    e.step(0.01, frame(pitch=1.0), 0.0)
    assert e.step(0.01, frame(pitch=0.15), 0.0).airspeed == 0.0


def test_state_carries_collective_and_deflection_and_zero_dt_holds() -> None:
    e = _est()
    e.step(0.01, frame(pitch=1.0, collective=0.7), 0.3)
    before = e.airspeed
    state = e.step(0.0, frame(pitch=1.0, collective=0.7), 0.3)
    assert (state.collective, state.deflection, state.airspeed) == (0.7, 0.3, before)


def test_negative_dt_counts_as_zero() -> None:
    e = _est()
    e.step(0.01, frame(pitch=1.0), 0.0)
    before = e.airspeed
    assert e.step(-1.0, frame(pitch=1.0), 0.0).airspeed == before


def test_restart_zeroes_the_estimate() -> None:
    e = InputEstimator(0.15, 0.0)
    e.step(0.01, frame(pitch=1.0), 0.0)
    e.restart()
    assert e.airspeed == 0.0


def test_flight_state_is_a_frozen_value() -> None:
    state = FlightState(airspeed=0.5, collective=0.2, deflection=0.1)
    with pytest.raises(AttributeError):
        state.airspeed = 1.0  # type: ignore[misc]


def test_rejects_threshold_of_one_and_negative_tau() -> None:
    with pytest.raises(ValueError, match="forward_threshold"):
        InputEstimator(1.0, 1.0)
    with pytest.raises(ValueError, match="forward_threshold"):
        InputEstimator(-0.1, 1.0)
    with pytest.raises(ValueError, match="tau_s"):
        InputEstimator(0.1, -1.0)
    with pytest.raises(ValueError, match="tau_s"):
        InputEstimator(0.1, float("nan"))
