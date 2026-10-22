import pytest

from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.weapon import WeaponModel, scaled

_WEAPONS = load_constants().weapons
MINIGUNS = _WEAPONS["littlebird_miniguns"]
ROCKETS_LB = _WEAPONS["littlebird_rockets"]
HAVOC_MG = _WEAPONS["havoc_mg"]


def _state(weapon: WeaponModel) -> str:
    """Current state widened to ``str`` so mypy does not narrow it between asserts."""
    return weapon.state


def test_minigun_winds_up_then_fires_at_25hz() -> None:
    w = WeaponModel(MINIGUNS, amplitude=0.5)
    assert w.step(0.25, True, False) == [] and _state(w) == "firing"
    rounds = w.step(1.0, True, False)
    assert len(rounds) == 25
    roll, pitch = scaled(MINIGUNS.recoil_pattern[0], MINIGUNS.recoil_pattern)
    assert rounds[0] == pytest.approx((roll * 0.5 * 0.15, pitch * 0.5 * 0.15))
    assert len(w.step(1.0, True, False)) == 25  # pattern wraps 7 -> 14 -> ...


def test_rockets_kick_rearward_at_game_rate() -> None:
    w = WeaponModel(ROCKETS_LB, amplitude=1.0)
    rounds = w.step(1.0, True, False)
    assert len(rounds) == 6 and all(r == (0.0, -1.0) for r in rounds)  # 350 rpm


def test_reload_silences_then_rewinds() -> None:
    w = WeaponModel(MINIGUNS, amplitude=1.0)
    w.step(0.5, True, False)
    assert w.step(0.1, True, True) == [] and _state(w) == "reloading"
    # 6.1 s into the 6.25 s window
    assert w.step(6.0, True, False) == [] and _state(w) == "reloading"
    assert w.step(0.2, True, False) == []  # window ends at 6.25; wind-up restarts
    assert _state(w) == "winding"
    w.step(0.25, True, False)
    assert len(w.step(0.2, True, False)) == 5


def test_release_resets_windup() -> None:
    w = WeaponModel(HAVOC_MG, amplitude=1.0)
    w.step(0.9, True, False)
    w.step(0.1, False, False)
    assert _state(w) == "idle"
    assert w.step(0.9, True, False) == []  # wind-up 1.0 s again


def test_pattern_steps_through_seven_vectors_and_wraps() -> None:
    w = WeaponModel(MINIGUNS, amplitude=1.0)
    w.step(0.25, True, False)
    rounds = w.step(0.04 * 8 - 0.001, True, False)
    assert len(rounds) == 8
    pattern = MINIGUNS.recoil_pattern
    for index in (0, 6, 7):
        yaw, pitch = scaled(pattern[index % 7], pattern)
        assert rounds[index] == pytest.approx((yaw * 0.15, pitch * 0.15))


def test_second_reload_tap_is_ignored_not_restarted() -> None:
    w = WeaponModel(ROCKETS_LB, amplitude=1.0)  # 7.0 s reload
    w.step(0.1, True, True)
    w.step(6.0, True, False)
    w.step(0.05, True, True)  # 6.15 s in; a restart would end the window at 13.05 s
    assert _state(w) == "reloading"
    w.step(0.8, False, False)  # 6.95 s: still inside the original window
    assert _state(w) == "reloading"
    w.step(0.1, False, False)  # 7.05 s: the original window has ended
    assert _state(w) == "idle"


def test_fire_released_during_reload_then_repressed_rewinds() -> None:
    w = WeaponModel(MINIGUNS, amplitude=1.0)  # 6.25 s reload, 0.25 s wind-up
    w.step(0.1, True, True)
    w.step(6.2, False, False)  # 6.3 s: window over, fire not held
    assert _state(w) == "idle"
    assert w.step(0.1, True, False) == [] and _state(w) == "winding"
    assert w.step(0.1, True, False) == [] and _state(w) == "winding"
    assert len(w.step(0.1, True, False)) >= 1  # wind-up ended 0.05 s in
    assert _state(w) == "firing"


def _total_rounds(w: WeaponModel, dt: float, ticks: int) -> int:
    return sum(len(w.step(dt, True, False)) for _ in range(ticks))


def test_fire_rate_is_exact_across_many_small_ticks() -> None:
    w = WeaponModel(MINIGUNS, amplitude=1.0)
    w.step(0.25, True, False)
    # Rounds at 0, 0.04, ..., 0.96; the one at exactly 1.00 s is the next tick's.
    assert _total_rounds(w, 0.01, 100) == 25


def test_fire_rate_is_exact_at_sixty_hertz_ticks() -> None:
    w = WeaponModel(MINIGUNS, amplitude=1.0)
    w.step(0.25, True, False)
    assert _total_rounds(w, 1 / 60, 60) == 25


def test_negative_dt_counts_as_zero() -> None:
    w = WeaponModel(ROCKETS_LB, amplitude=1.0)
    assert w.step(-1.0, True, False) == []
