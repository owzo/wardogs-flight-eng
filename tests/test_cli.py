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
from sdl_support import GUID_PEDALS, GUID_STICK, FakeSdl, pedals, stick

from wardogs_flight_eng import cli, cli_devices
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


def test_check_device_exit_code_reflects_report() -> None:
    passing = invoke(["check-device"], api=FakeSdl(pedals(), stick()))
    assert passing.code == 0
    assert "spring_center_moves" in passing.output and "MOZA AB9 Base" in passing.output
    partial = FakeSdl(stick(), supported=FakeSdl.SDL_HAPTIC_SPRING)
    failing = invoke(["check-device", "--guid", GUID_STICK], api=partial)
    assert failing.code == 1
    assert "constant" in failing.output and "no" in failing.output


def test_check_device_reports_conditions_and_warns_when_only_they_are_missing() -> None:
    legacy = FakeSdl(
        stick(),
        supported=FakeSdl.SDL_HAPTIC_CONSTANT
        | FakeSdl.SDL_HAPTIC_SINE
        | FakeSdl.SDL_HAPTIC_SPRING,
    )
    result = invoke(["check-device"], api=legacy)
    assert result.code == 0 and "WARN" in result.output and "friction" in result.output
    full = invoke(["check-device"], api=FakeSdl(stick()))
    assert full.code == 0 and "PASS" in full.output and "inertia" in full.output


def test_check_device_without_a_force_feedback_device_exits_2() -> None:
    assert invoke(["check-device"], api=FakeSdl(pedals())).code == 2
    unknown = invoke(["check-device", "--guid", "ffff"], api=FakeSdl(stick()))
    assert unknown.code == 2 and "ffff" in unknown.output


def test_check_device_on_a_device_without_haptics_exits_1() -> None:
    result = invoke(["check-device", "--guid", GUID_PEDALS], api=FakeSdl(pedals()))
    assert result.code == 1 and "force feedback" in result.output


def test_list_devices_prints_every_joystick() -> None:
    result = invoke(["list-devices"], api=FakeSdl(stick(), pedals()))
    assert result.code == 0
    stick_row = next(r for r in result.output.splitlines() if GUID_STICK in r)
    assert "MOZA AB9 Base" in stick_row and stick_row.split()[-1] == "yes"
    pedal_row = next(r for r in result.output.splitlines() if GUID_PEDALS in r)
    assert pedal_row.split()[-3:] == ["4", "2", "no"]
    assert "no joysticks" in invoke(["list-devices"]).output


def test_list_devices_live_shows_values_until_ctrl_c(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = stick()
    base.axes[1], base.buttons[1] = 16384, 1
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli_devices, "sleep", sleep)
    fake = FakeSdl(base)
    result = invoke(["list-devices", "--live"], api=fake)
    assert result.code == 0 and sleeps == [0.1, 0.1]
    live = [r for r in result.output.splitlines() if "+0.50" in r]
    assert len(live) == 2 and "held: 1" in live[0]
    assert fake.args("SDL_JoystickClose")[-1] == (GUID_STICK,)


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
