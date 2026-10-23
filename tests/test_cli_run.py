"""The ``run`` command against the fake SDL: wiring, exit codes and release."""

import json
import signal
from pathlib import Path

import pytest
from cli_support import (
    TickingSdl,
    bound_document,
    detach_all,
    invoke,
    joysticks_released,
    press_ctrl_c,
    write_profile,
)
from sdl_support import GUID_STICK, FakeJoystick, FakeSdl, pedals, stick

from wardogs_flight_eng import cli


@pytest.fixture(autouse=True)
def quiet_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "setup_logging", lambda verbose: None)


@pytest.fixture
def profile(tmp_path: Path) -> Path:
    return write_profile(tmp_path / "bird.json", bound_document())


def _bounded(*joysticks: FakeJoystick) -> TickingSdl:
    """A fake that detaches everything after 200 updates: a regression that
    reaches the loop ends with exit 2 instead of hanging the suite."""
    return TickingSdl(*joysticks, after=200, then=detach_all)


def _run(profile: Path, *extra: str) -> list[str]:
    return ["run", "--profile", str(profile), "--rate", "1000", *extra]


def _released(fake: FakeSdl) -> None:
    """Haptic closed first, then both joysticks; nothing touched afterwards."""
    names = fake.names()
    assert fake.count("SDL_HapticClose") == 1
    assert joysticks_released(fake)
    assert names[-2:] == ["SDL_JoystickClose", "SDL_JoystickClose"]
    assert names.index("SDL_HapticClose") < len(names) - 2


def test_ctrl_c_stops_cleanly_and_tees_the_force_log(
    profile: Path, tmp_path: Path
) -> None:
    log = tmp_path / "logs" / "forces.jsonl"
    fake = TickingSdl(stick(), pedals(), after=10, then=press_ctrl_c)
    result = invoke(_run(profile, "--log", str(log)), api=fake)
    assert result.code == 0 and "stopped: stop after" in result.output
    assert signal.getsignal(signal.SIGINT) is signal.default_int_handler
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert {"spring", "sine"} <= {row["kind"] for row in rows}
    assert rows[-1]["kind"] == "all_off"
    assert fake.count("SDL_HapticNewEffect") >= 2
    _released(fake)


def test_force_log_records_the_clamped_commands(tmp_path: Path) -> None:
    document = bound_document()
    document["feel"]["spring_coefficient"] = 0.9
    profile = write_profile(tmp_path / "stiff.json", document)
    log = tmp_path / "forces.jsonl"
    fake = TickingSdl(stick(), pedals(), after=10, then=press_ctrl_c)
    assert invoke(_run(profile, "--log", str(log)), api=fake).code == 0
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    springs = [row for row in rows if row["kind"] == "spring"]
    assert springs and max(row["coefficient"] for row in springs) <= 0.6


def test_device_lost_mid_run_exits_2_and_releases(profile: Path) -> None:
    fake = TickingSdl(stick(), pedals(), after=6, then=detach_all)
    result = invoke(_run(profile), api=fake)
    assert result.code == 2 and "device_lost" in result.output
    _released(fake)


def test_profiles_with_different_device_maps_exit_1(
    profile: Path, tmp_path: Path
) -> None:
    other = bound_document()
    other["device_map"]["axes"]["collective"]["axis"] = 1
    second = write_profile(tmp_path / "other.json", other)
    fake = _bounded(stick(), pedals())
    result = invoke(_run(profile, "--profile", str(second)), api=fake)
    assert result.code == 1 and "other.json" in result.output
    assert fake.count("SDL_JoystickOpen") == 0


def test_two_profiles_sharing_a_map_run(profile: Path, tmp_path: Path) -> None:
    document = bound_document()
    document["name"] = "second"
    second = write_profile(tmp_path / "second.json", document)
    fake = TickingSdl(stick(), pedals(), after=10, then=press_ctrl_c)
    assert invoke(_run(profile, "--profile", str(second)), api=fake).code == 0


def test_missing_device_exits_2_naming_it(profile: Path) -> None:
    fake = _bounded(stick())
    result = invoke(_run(profile), api=fake)
    assert result.code == 2 and "'pedals'" in result.output
    assert fake.args("SDL_JoystickClose")[-1] == (GUID_STICK,)


def test_device_found_by_product_when_guid_is_missing(tmp_path: Path) -> None:
    document = bound_document()
    document["device_map"]["devices"]["pedals"] = {"guid": None, "product": "rudder"}
    profile = write_profile(tmp_path / "bird.json", document)
    fake = TickingSdl(stick(), pedals(), after=10, then=press_ctrl_c)
    assert invoke(_run(profile), api=fake).code == 0


def test_force_axes_on_a_device_without_haptics_exit_1(profile: Path) -> None:
    base = stick()
    base.haptic = False
    fake = _bounded(base, pedals())
    result = invoke(_run(profile), api=fake)
    assert result.code == 1 and "pitch" in result.output
    assert "force feedback" in result.output
    assert joysticks_released(fake)


def test_pitch_and_roll_on_different_devices_exit_1(tmp_path: Path) -> None:
    document = bound_document()
    document["device_map"]["axes"]["roll"] = {"device": "pedals", "axis": 1}
    profile = write_profile(tmp_path / "split.json", document)
    result = invoke(_run(profile), api=_bounded(stick(), pedals()))
    assert result.code == 1 and "device_map.axes.roll" in result.output


def test_unbound_channel_exits_1_naming_it(tmp_path: Path) -> None:
    document = bound_document()
    del document["device_map"]["axes"]["pedals"]
    profile = write_profile(tmp_path / "nopedals.json", document)
    fake = _bounded(stick(), pedals())
    result = invoke(_run(profile), api=fake)
    assert result.code == 1 and "'pedals'" in result.output
    assert joysticks_released(fake)


def test_unwritable_log_exits_1_and_releases(profile: Path, tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("not a directory", encoding="utf-8")
    fake = _bounded(stick(), pedals())
    result = invoke(_run(profile, "--log", str(blocker / "forces.jsonl")), api=fake)
    assert result.code == 1
    _released(fake)


def test_non_positive_rate_is_a_usage_error(profile: Path) -> None:
    result = invoke(["run", "--profile", str(profile), "--rate", "0"])
    assert result.code == 1 and "--rate" in result.output
