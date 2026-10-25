"""Command-line interface: offline commands, device commands and calibrate."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cli_support import (
    PACKAGED,
    ScriptedStdin,
    bound_document,
    invoke,
    joysticks_released,
    packaged_document,
    write_profile,
)
from dry_run_support import SCENARIOS
from sdl_support import FakeSdl, pedals, stick

from wardogs_flight_eng import cli
from wardogs_flight_eng.constants.model import UNKNOWN


@pytest.fixture(autouse=True)
def quiet_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Record ``setup_logging`` calls instead of installing handlers."""
    calls: list[bool] = []
    monkeypatch.setattr(cli, "setup_logging", calls.append)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    return calls


def test_run_with_empty_device_map_exits_1_and_says_calibrate() -> None:
    fake = FakeSdl(stick(), pedals())
    result = invoke(["run", "--profile", str(PACKAGED)], api=fake)
    assert result.code == 1
    assert "list-devices --live" in result.output
    assert "calibrate" in result.output
    assert fake.count("SDL_JoystickOpen") == 0


def test_dry_run_writes_log_and_plot(tmp_path: Path) -> None:
    out = tmp_path / "out"
    scenario = SCENARIOS / "takeoff-trim-fire.json"
    argv = ["dry-run", "--profile", str(PACKAGED), "--scenario", str(scenario)]
    result = invoke([*argv, "--out", str(out)])
    assert result.code == 0
    assert (out / "forces.jsonl").stat().st_size > 0
    assert "<svg" in (out / "forces.html").read_text(encoding="utf-8")
    assert str(out / "forces.jsonl") in result.output
    assert str(out / "forces.html") in result.output


def test_dry_run_defaults_to_a_timestamped_config_dir(tmp_path: Path) -> None:
    scenario = SCENARIOS / "takeoff-trim-fire.json"
    argv = ["dry-run", "--profile", str(PACKAGED), "--scenario", str(scenario)]
    assert invoke(argv).code == 0
    runs = list((tmp_path / "appdata" / "WardogsFlightEng" / "dry-runs").iterdir())
    assert len(runs) == 1 and (runs[0] / "forces.html").exists()


def test_dry_run_with_unreadable_scenario_exits_1(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    argv = ["dry-run", "--profile", str(PACKAGED), "--scenario", str(missing)]
    result = invoke([*argv, "--out", str(tmp_path / "out")])
    assert result.code == 1 and "missing.json" in result.output


def test_show_constants_prints_unknown_sentinel() -> None:
    result = invoke(["show-constants"])
    assert result.code == 0
    assert "rounds_per_reload" in result.output
    assert "littlebird_miniguns" in result.output and "havoc" in result.output
    row = next(r for r in result.output.splitlines() if "littlebird_miniguns" in r)
    assert row.rstrip().endswith(UNKNOWN)


def test_verbose_reaches_setup_logging(quiet_logging: list[bool]) -> None:
    invoke(["show-constants", "--verbose"])
    invoke(["show-constants"])
    assert quiet_logging == [True, False]


def test_calibrate_rewrites_only_calibration(tmp_path: Path) -> None:
    original = bound_document()
    path = write_profile(tmp_path / "bird.json", original)
    base, rudder = stick(), pedals()

    def axis(joystick_axes: list[int], index: int, raw: int) -> None:
        joystick_axes[index] = raw

    stdin = ScriptedStdin(
        lambda: axis(base.axes, 2, -30000),
        lambda: axis(base.axes, 2, 31000),
        lambda: axis(rudder.axes, 0, 1200),
    )
    result = invoke(["calibrate", "--profile", str(path)], FakeSdl(base, rudder), stdin)
    assert result.code == 0 and stdin.reads == 3
    assert "fully down" in result.output and "centred" in result.output
    rewritten = json.loads(path.read_text(encoding="utf-8"))
    assert rewritten["device_map"].pop("calibration") == {
        "collective_bottom_raw": round(-30000 / 32767, 4),
        "collective_top_raw": round(31000 / 32767, 4),
        "pedals_center_raw": round(1200 / 32767, 4),
    }
    del original["device_map"]["calibration"]
    assert rewritten == original
    assert list(rewritten) == list(original)
    assert path.read_text(encoding="utf-8").startswith('{\n  "name"')


def test_calibrate_aborts_without_writing_when_stdin_closes(tmp_path: Path) -> None:
    path = write_profile(tmp_path / "bird.json", bound_document())
    before = path.read_text(encoding="utf-8")
    api = FakeSdl(stick(), pedals())
    result = invoke(["calibrate", "--profile", str(path)], api, ScriptedStdin())
    assert result.code == 1 and path.read_text(encoding="utf-8") == before
    assert joysticks_released(api)


def test_calibrate_rejects_an_unmoved_collective(tmp_path: Path) -> None:
    path = write_profile(tmp_path / "bird.json", bound_document())
    before = path.read_text(encoding="utf-8")
    stdin = ScriptedStdin(lambda: None, lambda: None, lambda: None)
    result = invoke(
        ["calibrate", "--profile", str(path)], FakeSdl(stick(), pedals()), stdin
    )
    assert result.code == 1 and "collective" in result.output
    assert path.read_text(encoding="utf-8") == before


def test_calibrate_needs_collective_and_pedals_bound(tmp_path: Path) -> None:
    path = write_profile(tmp_path / "bird.json", packaged_document())
    result = invoke(["calibrate", "--profile", str(path)])
    assert result.code == 1 and "device_map.axes.collective" in result.output


def test_invalid_profile_exits_1_naming_the_field(tmp_path: Path) -> None:
    document = bound_document()
    document["feel"]["spring_coefficient"] = 2.0
    path = write_profile(tmp_path / "bad.json", document)
    result = invoke(["calibrate", "--profile", str(path)])
    assert result.code == 1 and "feel.spring_coefficient" in result.output


def test_usage_errors_exit_1() -> None:
    assert invoke(["fly"]).code == 1
    missing = invoke(["run"])
    assert missing.code == 1 and "--profile" in missing.output


def test_module_entry_point_runs_the_cli(tmp_path: Path) -> None:
    env = {**os.environ, "LOCALAPPDATA": str(tmp_path)}
    done = subprocess.run(
        [sys.executable, "-m", "wardogs_flight_eng", "show-constants"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert done.returncode == 0 and UNKNOWN in done.stdout
