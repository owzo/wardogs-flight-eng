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
    assert springs_after_lock[0]["center"] == pytest.approx(0.3, abs=0.01)
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
