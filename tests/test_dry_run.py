"""Scenario dry run: simulated devices -> engine -> force log -> plot."""

import json
from pathlib import Path
from typing import Any

import pytest
from dry_run_support import SCENARIOS, profile

from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.commands import Command
from wardogs_flight_eng.engine.synth import FlightEngine
from wardogs_flight_eng.inputs.simulated import Scenario
from wardogs_flight_eng.runtime.dry_run import dry_run


def _run(tmp_path: Path) -> tuple[Path, Path]:
    scenario = Scenario.load(SCENARIOS / "takeoff-trim-fire.json")
    return dry_run(profile("littlebird-miniguns"), load_constants(), scenario, tmp_path)


def _rows(log: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_dry_run_log_shows_trim_lock_and_fire(tmp_path: Path) -> None:
    log, plot = _run(tmp_path)
    rows = _rows(log)
    springs_after_lock = [
        r
        for r in rows
        if r["kind"] == "spring" and r["axis"] == "pitch" and r["t"] > 5.5
    ]
    # Unboosted Littlebird: the lock clamps the stick (spring faded out,
    # friction at clamp_friction 0.5) instead of moving the spring centre.
    lock = springs_after_lock[0]
    assert (lock["center"], lock["coefficient"]) == (0.0, 0.0)
    friction = [
        r
        for r in rows
        if r["kind"] == "friction" and r["axis"] == "pitch" and r["t"] > 5.5
    ]
    assert friction[0]["coefficient"] == pytest.approx(0.5)
    pulses = [r for r in rows if r["kind"] == "pulse" and 7.3 < r["t"] < 9.0]
    # 25 rounds/s for ~1.7 s after the 0.25 s wind-up = 42 rounds, each a pitch
    # and a roll pulse: 84 pulses in all, 42 per axis.
    assert 80 <= len(pulses) <= 90
    assert {a: sum(r["axis"] == a for r in pulses) for a in ("pitch", "roll")} == {
        "pitch": 42,
        "roll": 42,
    }
    assert plot.exists() and "<svg" in plot.read_text()


def test_dry_run_writes_both_outputs_into_a_new_directory(tmp_path: Path) -> None:
    out_dir = tmp_path / "nested" / "run"
    scenario = Scenario.load(SCENARIOS / "takeoff-trim-fire.json")
    log, plot = dry_run(
        profile("littlebird-miniguns"), load_constants(), scenario, out_dir
    )
    assert log == out_dir / "forces.jsonl"
    assert plot == out_dir / "forces.html"


def test_dry_run_ticks_are_exactly_one_period_apart(tmp_path: Path) -> None:
    log, _ = _run(tmp_path)
    times = sorted({r["t"] for r in _rows(log)})
    assert len(times) == 1200  # int(12 s * 100 Hz) ticks, one distinct time each
    assert times[0] == 0.0
    assert times[-1] == pytest.approx(11.99)
    assert all(t == n / 100 for n, t in enumerate(times))


def test_dry_run_never_trips_the_watchdog(tmp_path: Path) -> None:
    log, _ = _run(tmp_path)
    assert not any(r["kind"] == "all_off" for r in _rows(log)[:-1])


def test_dry_run_fails_loudly_when_the_loop_stops_early(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_step(*_args: object) -> list[Command]:
        raise ValueError("engine blew up")

    monkeypatch.setattr(FlightEngine, "step", broken_step)
    with pytest.raises(RuntimeError, match="ended early.*error"):
        _run(tmp_path)


def _clamp_run(tmp_path: Path) -> list[dict[str, Any]]:
    scenario = Scenario.load(SCENARIOS / "littlebird-clamp-cruise.json")
    log, _ = dry_run(
        profile("littlebird-miniguns"), load_constants(), scenario, tmp_path
    )
    return _rows(log)


def _at(rows: list[dict[str, Any]], kind: str, axis: str, t: float) -> dict[str, Any]:
    """The record of ``kind`` on ``axis`` nearest to ``t``."""
    return min(
        (r for r in rows if r["kind"] == kind and r["axis"] == axis),
        key=lambda r: abs(r["t"] - t),
    )


def test_dry_run_clamp_swaps_spring_for_friction_and_back(tmp_path: Path) -> None:
    rows = _clamp_run(tmp_path)
    friction, spring = (
        _at(rows, "friction", "pitch", 9.0),
        _at(rows, "spring", "pitch", 9.0),
    )
    assert (friction["coefficient"], spring["coefficient"]) == (0.02, 0.12)
    assert _at(rows, "friction", "pitch", 11.0)["coefficient"] == pytest.approx(0.5)
    assert _at(rows, "spring", "pitch", 11.0)["coefficient"] == 0.0
    assert _at(rows, "spring", "pitch", 11.0)["center"] == 0.0
    assert _at(rows, "spring", "pitch", 15.0)["coefficient"] == 0.12
    assert _at(rows, "friction", "pitch", 15.0)["coefficient"] == 0.02


def test_dry_run_buzz_grows_with_the_airspeed_estimate(tmp_path: Path) -> None:
    rows = _clamp_run(tmp_path)
    early = _at(rows, "sine", "pitch", 4.05)["magnitude"]
    late = _at(rows, "sine", "pitch", 9.9)["magnitude"]
    # Airspeed 0.41 x factor 0.6 after 5.9 s at tau 4 s; spool and collective equal.
    assert late > 1.15 * early


def test_dry_run_lakota_conditions_are_constant(tmp_path: Path) -> None:
    scenario = Scenario.load(SCENARIOS / "takeoff-trim-fire.json")
    log, _ = dry_run(profile("lakota"), load_constants(), scenario, tmp_path)
    rows = _rows(log)
    dampers = {
        r["coefficient"] for r in rows if r["kind"] == "damper" and r["axis"] == "pitch"
    }
    frictions = [
        r["coefficient"]
        for r in rows
        if r["kind"] == "friction" and r["axis"] == "roll"
    ]
    assert dampers == {0.25}
    assert frictions and frictions == pytest.approx([0.05] * len(frictions))


def test_dry_run_rounds_a_hand_written_duration_to_whole_ticks(
    tmp_path: Path,
) -> None:
    raw = json.loads((SCENARIOS / "takeoff-trim-fire.json").read_text())
    raw["rate_hz"] = 30.0
    raw["steps"] = [raw["steps"][0], {"t": 4.1, "set": {}}]  # 4.1 * 30 < 123
    path = tmp_path / "short.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    scenario = Scenario.load(path)
    log, _ = dry_run(
        profile("littlebird-miniguns"), load_constants(), scenario, tmp_path
    )
    assert len({r["t"] for r in _rows(log)}) == 123
