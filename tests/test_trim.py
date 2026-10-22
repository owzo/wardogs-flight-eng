"""Trim state: lock/reset move the spring centre, slewed, and nothing else does."""

import pytest

from wardogs_flight_eng.engine.trim import TrimState


def test_lock_then_reset_slews_over_slew_time() -> None:
    t = TrimState(slew_s=0.5)
    t.lock(0.5, -0.25)
    t.step(0.25)
    assert t.center_pitch == pytest.approx(0.25)
    assert t.center_roll == pytest.approx(-0.125)
    t.step(1.0)
    assert (t.center_pitch, t.center_roll) == (0.5, -0.25)
    t.reset()
    t.step(10)
    assert (t.center_pitch, t.center_roll) == (0.0, 0.0)


def test_lock_at_full_deflection_clamps_to_unit() -> None:  # Review Focus 3
    t = TrimState(slew_s=0)
    t.lock(1.7, -3.0)
    t.step(0)
    assert (t.center_pitch, t.center_roll) == (1.0, -1.0)


def test_nothing_but_lock_and_reset_moves_center() -> None:
    t = TrimState(slew_s=0)
    t.step(5.0)
    assert (t.center_pitch, t.center_roll) == (0.0, 0.0)
