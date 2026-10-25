"""The ``run`` command: device-map, binding and log-path validation."""

from pathlib import Path

import pytest
from cli_run_support import bounded, released, run_args
from cli_support import (
    TickingSdl,
    bound_document,
    invoke,
    joysticks_released,
    press_ctrl_c,
    write_profile,
)
from sdl_support import GUID_STICK, pedals, stick

from wardogs_flight_eng import cli


@pytest.fixture(autouse=True)
def quiet_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "setup_logging", lambda verbose: None)


@pytest.fixture
def profile(tmp_path: Path) -> Path:
    return write_profile(tmp_path / "bird.json", bound_document())


def test_profiles_with_different_device_maps_exit_1(
    profile: Path, tmp_path: Path
) -> None:
    other = bound_document()
    other["device_map"]["axes"]["collective"]["axis"] = 1
    second = write_profile(tmp_path / "other.json", other)
    fake = bounded(stick(), pedals())
    result = invoke(run_args(profile, "--profile", str(second)), api=fake)
    assert result.code == 1 and "other.json" in result.output
    assert "device_map.axes.collective.axis" in result.output
    assert fake.count("SDL_JoystickOpen") == 0


def test_calibration_drift_between_profiles_names_the_key(
    profile: Path, tmp_path: Path
) -> None:
    other = bound_document()
    other["device_map"]["calibration"]["collective_bottom_raw"] = -0.9
    second = write_profile(tmp_path / "drift.json", other)
    result = invoke(run_args(profile, "--profile", str(second)), api=bounded())
    assert result.code == 1
    assert "device_map.calibration.collective_bottom_raw" in result.output


def test_two_profiles_sharing_a_map_run(profile: Path, tmp_path: Path) -> None:
    document = bound_document()
    document["name"] = "second"
    second = write_profile(tmp_path / "second.json", document)
    fake = TickingSdl(stick(), pedals(), after=10, then=press_ctrl_c)
    assert invoke(run_args(profile, "--profile", str(second)), api=fake).code == 0


def test_missing_device_exits_2_naming_it(profile: Path) -> None:
    fake = bounded(stick())
    result = invoke(run_args(profile), api=fake)
    assert result.code == 2 and "'pedals'" in result.output
    assert fake.args("SDL_JoystickClose")[-1] == (GUID_STICK,)


def test_device_found_by_product_when_guid_is_missing(tmp_path: Path) -> None:
    document = bound_document()
    document["device_map"]["devices"]["pedals"] = {"guid": None, "product": "rudder"}
    profile = write_profile(tmp_path / "bird.json", document)
    fake = TickingSdl(stick(), pedals(), after=10, then=press_ctrl_c)
    assert invoke(run_args(profile), api=fake).code == 0


def test_force_axes_on_a_device_without_haptics_exit_1(profile: Path) -> None:
    base = stick()
    base.haptic = False
    fake = bounded(base, pedals())
    result = invoke(run_args(profile), api=fake)
    assert result.code == 1 and "pitch" in result.output
    assert "force feedback" in result.output
    assert joysticks_released(fake)


def test_pitch_and_roll_on_different_devices_exit_1(tmp_path: Path) -> None:
    document = bound_document()
    document["device_map"]["axes"]["roll"] = {"device": "pedals", "axis": 1}
    profile = write_profile(tmp_path / "split.json", document)
    result = invoke(run_args(profile), api=bounded(stick(), pedals()))
    assert result.code == 1 and "device_map.axes.roll" in result.output


def test_unbound_channel_exits_1_naming_it(tmp_path: Path) -> None:
    document = bound_document()
    del document["device_map"]["axes"]["pedals"]
    profile = write_profile(tmp_path / "nopedals.json", document)
    fake = bounded(stick(), pedals())
    result = invoke(run_args(profile), api=fake)
    assert result.code == 1 and "'pedals'" in result.output
    assert joysticks_released(fake)


def test_unwritable_log_exits_1_and_releases(profile: Path, tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory", encoding="utf-8")
    fake = bounded(stick(), pedals())
    result = invoke(run_args(profile, "--log", str(blocker / "forces.jsonl")), api=fake)
    assert result.code == 1
    released(fake)


def test_non_positive_rate_is_a_usage_error(profile: Path) -> None:
    result = invoke(["run", "--profile", str(profile), "--rate", "0"])
    assert result.code == 1 and "--rate" in result.output
