"""Device commands: ``check-device`` and ``list-devices``."""

from pathlib import Path

import pytest
from cli_support import (
    invoke,
)
from sdl_support import GUID_PEDALS, GUID_STICK, FakeSdl, pedals, stick

from wardogs_flight_eng import cli, cli_devices


@pytest.fixture(autouse=True)
def quiet_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Record ``setup_logging`` calls instead of installing handlers."""
    calls: list[bool] = []
    monkeypatch.setattr(cli, "setup_logging", calls.append)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    return calls


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
    assert result.code == 0
    assert (
        "WARN: not accepted: friction, damper, inertia "
        f"({cli_devices.CONDITION_WARNING})" in result.output
    )
    assert cli_devices.CONDITION_WARNING == (
        "unboosted profiles cannot run without friction; "
        "force_trim profiles run without the missing conditions"
    )
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
