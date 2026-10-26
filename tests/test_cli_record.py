"""``record``: raw controls to a scenario file, with no force output at all."""

import json
from pathlib import Path

import pytest
from cli_support import (
    TickingSdl,
    bound_document,
    detach_all,
    interrupt,
    invoke,
    joysticks_released,
    packaged_document,
    press_ctrl_c,
    write_profile,
)
from sdl_support import FakeSdl, pedals, stick

from wardogs_flight_eng import cli
from wardogs_flight_eng.engine.device_map import DeviceMap
from wardogs_flight_eng.inputs.simulated import Scenario


@pytest.fixture(autouse=True)
def quiet_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "setup_logging", lambda verbose: None)


@pytest.fixture
def profile(tmp_path: Path) -> Path:
    return write_profile(tmp_path / "bird.json", bound_document())


def _record(profile: Path, out: Path, *extra: str) -> list[str]:
    return ["record", "--profile", str(profile), "--out", str(out), *extra]


def test_record_never_opens_haptics_and_writes_a_loadable_scenario(
    profile: Path, tmp_path: Path
) -> None:
    fake = TickingSdl(stick(), pedals(), after=30, then=detach_all)
    out = tmp_path / "flight.json"
    args = _record(profile, out, "--duration", "0.1", "--rate", "100")
    result = invoke(args, api=fake)
    assert result.code == 0, result.output
    assert fake.count("SDL_HapticOpenFromJoystick") == 0
    assert fake.count("SDL_HapticNewEffect") == 0
    assert out.exists() and Scenario.load(out).rate_hz == 100.0
    assert joysticks_released(fake)
    assert f"recorded 10 ticks (0.10 s), 2 steps -> {out}" in result.output


def test_recorded_file_holds_every_initial_value_and_the_closing_step(
    profile: Path, tmp_path: Path
) -> None:
    out = tmp_path / "flight.json"
    result = invoke(
        _record(profile, out, "--duration", "0.05"), api=FakeSdl(stick(), pedals())
    )
    assert result.code == 0, result.output
    doc = json.loads(out.read_text(encoding="utf-8"))
    bound = DeviceMap.model_validate(bound_document()["device_map"])
    assert doc["device_map"] == bound.model_dump(mode="json")
    assert doc["devices"] == {
        "base": {"axes": 3, "buttons": 2},
        "pedals": {"axes": 4, "buttons": 2},
    }
    first, last = doc["steps"][0], doc["steps"][-1]
    assert (
        first["t"] == 0.0
        and "base.axis0" in first["set"]
        and "pedals.axis3" in first["set"]
    )
    assert last == {"t": 0.05, "set": {}}


def test_record_writes_a_partial_file_and_exits_2_on_device_loss(
    profile: Path, tmp_path: Path
) -> None:
    fake = TickingSdl(stick(), pedals(), after=5, then=detach_all)
    out = tmp_path / "f.json"
    result = invoke(_record(profile, out), api=fake)
    assert result.code == 2 and out.exists()
    assert Scenario.load(out).duration_s > 0.0
    assert joysticks_released(fake)


def test_ctrl_c_ends_the_recording_cleanly(profile: Path, tmp_path: Path) -> None:
    fake = TickingSdl(stick(), pedals(), after=8, then=press_ctrl_c)
    out = tmp_path / "f.json"
    result = invoke(_record(profile, out), api=fake)
    assert result.code == 0 and Scenario.load(out).rate_hz == 100.0
    assert joysticks_released(fake)


def test_record_works_without_collective_or_pedals_bound(tmp_path: Path) -> None:
    doc = bound_document()
    del doc["device_map"]["axes"]["pedals"]
    del doc["device_map"]["axes"]["collective"]
    profile = write_profile(tmp_path / "bird.json", doc)
    out = tmp_path / "f.json"
    result = invoke(
        _record(profile, out, "--duration", "0.05"), api=FakeSdl(stick(), pedals())
    )
    assert result.code == 0, result.output
    assert Scenario.load(out).duration_s == 0.05


def test_default_calibration_is_warned_about(
    profile: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out = tmp_path / "f.json"
    invoke(_record(profile, out, "--duration", "0.02"), api=FakeSdl(stick(), pedals()))
    assert "default calibration" in caplog.text


def test_record_refuses_a_profile_without_devices(tmp_path: Path) -> None:
    profile = write_profile(tmp_path / "bird.json", packaged_document())
    result = invoke(_record(profile, tmp_path / "f.json"), api=FakeSdl(stick()))
    assert result.code == 1 and "device_map" in result.output
    assert not (tmp_path / "f.json").exists()


def test_record_rejects_a_non_positive_duration(profile: Path, tmp_path: Path) -> None:
    result = invoke(_record(profile, tmp_path / "f.json", "--duration", "0"))
    assert result.code == 1 and "--duration" in result.output


@pytest.mark.parametrize("value", ["nan", "inf", "-1"])
def test_record_rejects_a_bad_min_change(
    profile: Path, tmp_path: Path, value: str
) -> None:
    result = invoke(_record(profile, tmp_path / "f.json", "--min-change", value))
    assert result.code == 1 and "--min-change" in result.output
    assert not (tmp_path / "f.json").exists()


def test_a_forced_interrupt_still_writes_the_partial_file(
    profile: Path, tmp_path: Path
) -> None:
    fake = TickingSdl(stick(), pedals(), after=6, then=lambda _fake: interrupt())
    out = tmp_path / "f.json"
    result = invoke(_record(profile, out), api=fake)
    assert result.code == 1 and Scenario.load(out).duration_s > 0.0
    assert joysticks_released(fake)


def test_record_refuses_to_overwrite_its_profile(profile: Path) -> None:
    before = profile.read_bytes()
    fake = FakeSdl(stick(), pedals())
    result = invoke(_record(profile, profile, "--duration", "0.02"), api=fake)
    assert result.code == 1
    assert f"--out {profile}: refuses to overwrite the profile it reads" in (
        result.output
    )
    assert profile.read_bytes() == before
    assert fake.count("SDL_JoystickOpen") == 0


def test_record_leaves_no_staging_file(profile: Path, tmp_path: Path) -> None:
    out = tmp_path / "flight.json"
    args = _record(profile, out, "--duration", "0.02")
    assert invoke(args, api=FakeSdl(stick(), pedals())).code == 0
    assert out.exists() and not list(tmp_path.glob("*.tmp"))


def test_record_stages_under_a_unique_name(profile: Path, tmp_path: Path) -> None:
    out = tmp_path / "flight.json"
    stale = tmp_path / "flight.json.tmp"
    stale.write_text("another writer's staging file", encoding="utf-8")
    args = _record(profile, out, "--duration", "0.02")
    assert invoke(args, api=FakeSdl(stick(), pedals())).code == 0
    assert Scenario.load(out).rate_hz == 100.0
    assert stale.read_text(encoding="utf-8") == "another writer's staging file"
    assert list(tmp_path.glob("*.tmp")) == [stale]
