"""Rotor model: spool-up/down of main-rotor RPM and the buzz amplitude."""

import pytest

from wardogs_flight_eng.engine.rotor import RotorModel


def test_spools_up_to_operating_rpm() -> None:
    r = RotorModel(
        330.4,
        spool_up_s=2.0,
        spool_down_rpm_per_s=850,
        base_amplitude=0.3,
        deflection_factor=0.5,
    )
    r.step(1.0)
    assert r.rpm == pytest.approx(165.2)
    r.step(5.0)
    assert r.frequency_hz == pytest.approx(5.5067, abs=1e-3)


def test_spool_down_uses_game_rate() -> None:
    r = RotorModel(330.4, 2.0, 850, 0.3, 0.5)
    r.step(10)
    r.toggle()
    r.step(0.2)
    assert r.rpm == pytest.approx(330.4 - 170)
    r.step(10)
    assert r.rpm == 0


def test_amplitude_follows_collective_and_deflection() -> None:
    r = RotorModel(270, 0, 850, 0.4, 0.5)
    r.step(0)
    assert r.amplitude(0.0, 0.0) == 0
    assert r.amplitude(1.0, 0.0) == pytest.approx(0.4)
    assert r.amplitude(1.0, 1.0) == pytest.approx(0.6)


def test_starts_running_from_zero_rpm_and_toggles_back_up() -> None:
    r = RotorModel(300, 2.0, 100, 0.3, 0.5)
    assert r.running is True
    assert r.rpm == 0
    r.step(2.0)
    r.toggle()
    assert r.running is False
    r.step(1.0)
    assert r.rpm == pytest.approx(200)
    r.toggle()
    r.step(0.5)
    assert r.rpm == pytest.approx(275)


def test_negative_dt_counts_as_zero() -> None:
    r = RotorModel(300, 2.0, 100, 0.3, 0.5)
    r.step(1.0)
    r.step(-5.0)
    assert r.rpm == pytest.approx(150)


def test_amplitude_is_clamped_to_unit_range() -> None:
    r = RotorModel(270, 0, 850, 0.9, 1.0)
    r.step(0)
    assert r.amplitude(1.0, 1.0) == 1.0
    assert r.amplitude(-1.0, 0.0) == 0.0


def test_amplitude_scales_with_spool_fraction() -> None:
    r = RotorModel(300, 2.0, 100, 0.4, 0.5)
    r.step(1.0)
    assert r.amplitude(1.0, 0.0) == pytest.approx(0.2)


@pytest.mark.parametrize(
    "args",
    [
        (0, 1, 1, 0.3, 0.5),
        (-1, 1, 1, 0.3, 0.5),
        (300, -1, 1, 0.3, 0.5),
        (300, 1, -1, 0.3, 0.5),
        (300, 1, 1, -0.3, 0.5),
        (300, 1, 1, 0.3, -0.5),
    ],
)
def test_rejects_invalid_constructor_arguments(
    args: tuple[float, float, float, float, float],
) -> None:
    with pytest.raises(ValueError):
        RotorModel(*args)


def test_amplitude_grows_with_airspeed_factor() -> None:
    r = RotorModel(
        300, 0, 850, base_amplitude=0.4, deflection_factor=0.5, airspeed_factor=0.6
    )
    r.step(0.01)
    assert r.amplitude(1.0, 0.0, airspeed=0.5) == pytest.approx(0.4 * 1.3)
    assert r.amplitude(1.0, 0.0) == pytest.approx(0.4)  # default airspeed 0


def test_airspeed_factor_is_clamped_to_unit_range() -> None:
    r = RotorModel(
        300, 0, 850, base_amplitude=0.4, deflection_factor=0.0, airspeed_factor=2.0
    )
    r.step(0.01)
    assert r.amplitude(1.0, 1.0, airspeed=1.0) == 1.0  # raw 1.2: the airspeed term
    assert r.amplitude(1.0, 1.0) == pytest.approx(0.4)


def test_take_over_copies_spool_fraction_into_this_rotor_speed() -> None:
    r = RotorModel(250, 0, 850, 0.3, 0.5)
    r.take_over(0.5, running=False)
    assert (r.rpm, r.running, r.spool_fraction) == (125.0, False, 0.5)
    r.take_over(1.7, running=True)
    assert r.rpm == 250.0
    r.take_over(-0.5, running=True)
    assert r.rpm == 0.0


def test_rejects_negative_airspeed_factor() -> None:
    with pytest.raises(ValueError, match="airspeed_factor"):
        RotorModel(300, 0, 850, 0.3, 0.5, airspeed_factor=-0.1)


def test_buzz_below_the_floor_is_silenced() -> None:
    r = RotorModel(300, 0, 850, 0.4, 0.0, min_amplitude=0.1)
    r.step(0.01)
    assert r.amplitude(0.2, 0.0) == 0.0  # 0.08 < 0.1


def test_buzz_at_the_floor_plays() -> None:
    r = RotorModel(300, 0, 850, 0.5, 0.0, min_amplitude=0.25)
    r.step(0.01)
    assert r.amplitude(0.5, 0.0) == 0.25  # exactly representable: the >= edge


@pytest.mark.parametrize("floor", [-0.1, 1.1])
def test_min_amplitude_outside_unit_range_is_rejected(floor: float) -> None:
    with pytest.raises(ValueError, match="min_amplitude"):
        RotorModel(300, 0, 850, 0.4, 0.0, min_amplitude=floor)
