"""``check-device`` and ``list-devices`` with ``--backend dinput8``."""

import dataclasses

import pytest
from cli_dinput_support import CHECK, LEGACY, base, dinput8, on_windows, released
from cli_support import invoke
from dinput_support import FakeDirectInput, ab9

from wardogs_flight_eng import cli_dinput_devices
from wardogs_flight_eng.cli_console import CliError
from wardogs_flight_eng.inputs.dinput_api import DIERR_INVALIDPARAM


@pytest.fixture(autouse=True)
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    on_windows(monkeypatch)


def test_check_device_dinput8_passes_naming_instance_gain_and_axes() -> None:
    di = FakeDirectInput(base())
    result = invoke(CHECK, dinput_api=di)
    assert result.code == 0, result.output
    assert "device: MOZA AB9 Base (acquired, gain 10000)" in result.output
    y_row = next(r for r in result.output.splitlines() if "Y Axis" in r)
    assert y_row.split()[0] == "1" and "DIJOFS_Y" in y_row and "yes" in y_row
    assert "PASS" in result.output and di.count("start") == 0
    assert di.count("release_effect") == di.count("create_effect") == 6
    released(di)


def test_dinput_probe_reports_a_failed_centre_update() -> None:
    di = FakeDirectInput(base())
    di.fail["set_parameters"] = DIERR_INVALIDPARAM
    result = invoke(CHECK, dinput_api=di)
    assert result.code == 1
    moves = next(r for r in result.output.splitlines() if "spring_center_moves" in r)
    assert moves.split()[-1] == "no" and "FAIL" in result.output
    _, _, norestart = di.args("set_parameters")[0]
    assert norestart is False and di.count("start") == 0
    assert di.count("release_effect") == 6
    released(di)


def test_check_device_dinput8_warns_when_only_conditions_are_missing() -> None:
    di = FakeDirectInput(base(LEGACY))
    result = invoke(CHECK, dinput_api=di)
    assert result.code == 0 and "WARN: not accepted: friction" in result.output


def test_check_device_dinput8_needs_the_guid() -> None:
    di = FakeDirectInput(base())
    result = invoke(dinput8(["check-device"]), dinput_api=di)
    assert result.code == 1 and "--guid" in result.output and di.calls == []


def test_list_devices_dinput8_prints_the_instances() -> None:
    plain = dataclasses.replace(ab9(), instance_name="Pedals HID", force_feedback=False)
    di = FakeDirectInput(base(), plain)
    result = invoke(dinput8(["list-devices"]), dinput_api=di)
    assert result.code == 0
    row = next(r for r in result.output.splitlines() if "MOZA AB9 Base" in r)
    assert "1234:ab01" in row and row.split()[-1] == "yes"
    assert "346e:0010" in result.output and di.names() == ["close"]


def test_list_devices_dinput8_live_shows_axes_until_ctrl_c(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli_dinput_devices, "sleep", sleep)
    device = base()
    device.axes.append(dataclasses.replace(device.axes[0], offset=64, name="Force X"))
    device.state = dataclasses.replace(
        device.state, axes=(65535, *device.state.axes[1:])
    )
    di = FakeDirectInput(device)
    result = invoke(dinput8(["list-devices", "--live"]), dinput_api=di)
    assert result.code == 0 and sleeps == [0.1, 0.1]
    assert result.output.count("unreadable: Force X") == 1
    x_rows = [r for r in result.output.splitlines() if "X Axis" in r]
    assert x_rows == ["0 0 DIJOFS_X X Axis yes +1.00"] * 2
    released(di)


def test_the_real_adapter_is_not_in_this_build() -> None:
    with pytest.raises(CliError, match="DirectInput adapter is not available"):
        cli_dinput_devices.real_dinput_api()
