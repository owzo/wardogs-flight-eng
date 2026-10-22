"""SDL joystick input against the fake SDL: enumeration, open by GUID, reads."""

import subprocess
import sys

import pytest
from sdl_support import GUID_PEDALS, GUID_STICK, FakeSdl, pedals, stick

from wardogs_flight_eng.inputs.protocol import InputConfigError, InputDevice
from wardogs_flight_eng.inputs.sdl_api import SdlError
from wardogs_flight_eng.inputs.sdl_device import (
    DeviceInfo,
    SdlDevice,
    enumerate_devices,
    open_by_guid,
)


def test_enumerate_reports_each_joystick_and_releases_it() -> None:
    fake = FakeSdl(stick(), pedals())
    found = enumerate_devices(fake)
    assert found == [
        DeviceInfo(0, GUID_STICK, "MOZA AB9 Base", 3, 2, True),
        DeviceInfo(1, GUID_PEDALS, "Rudder Pedals", 4, 2, False),
    ]
    assert fake.args("SDL_Init") == [(fake.SDL_INIT_JOYSTICK | fake.SDL_INIT_HAPTIC,)]
    assert fake.args("SDL_JoystickClose") == [(GUID_STICK,), (GUID_PEDALS,)]


def test_init_failure_raises_sdl_error() -> None:
    fake = FakeSdl(stick())
    fake.init_result = -1
    with pytest.raises(SdlError, match="fake SDL error"):
        enumerate_devices(fake)


def test_open_by_guid_keeps_only_the_match_open() -> None:
    fake = FakeSdl(pedals(), stick())
    device = open_by_guid(GUID_STICK.upper(), fake)
    assert isinstance(device, SdlDevice)
    assert (device.guid, device.name, device.axis_count) == (
        GUID_STICK,
        "MOZA AB9 Base",
        3,
    )
    assert fake.args("SDL_JoystickClose") == [(GUID_PEDALS,)]


def test_open_by_unknown_guid_raises_config_error() -> None:
    fake = FakeSdl(pedals())
    with pytest.raises(InputConfigError, match="no joystick"):
        open_by_guid(GUID_STICK, fake)
    assert fake.args("SDL_JoystickClose") == [(GUID_PEDALS,)]


def test_axis_scaled_to_unit() -> None:
    joystick = stick()
    joystick.axes = [16383, -32768, 32767]
    device: InputDevice = open_by_guid(GUID_STICK, FakeSdl(joystick))
    assert device.axis(0) == pytest.approx(0.49998, abs=1e-5)
    assert device.axis(1) == -1.0
    assert device.axis(2) == 1.0


def test_poll_updates_and_buttons_read_pressed() -> None:
    joystick = stick()
    fake = FakeSdl(joystick)
    device = open_by_guid(GUID_STICK, fake)
    joystick.buttons = [0, 1]
    device.poll()
    assert fake.count("SDL_JoystickUpdate") == 1
    assert (device.button(0), device.button(1)) == (False, True)


def test_alive_follows_attached_on_poll() -> None:
    joystick = stick()
    device = open_by_guid(GUID_STICK, FakeSdl(joystick))
    assert device.alive
    joystick.attached = False
    device.poll()
    assert not device.alive


def test_close_releases_joystick_once() -> None:
    fake = FakeSdl(stick())
    device = open_by_guid(GUID_STICK, fake)
    device.close()
    device.close()
    assert fake.args("SDL_JoystickClose") == [(GUID_STICK,)]
    assert not device.alive


def test_importing_sdl_modules_does_not_load_sdl2() -> None:
    code = (
        "import sys\n"
        "import wardogs_flight_eng.inputs.sdl_device\n"
        "import wardogs_flight_eng.outputs.sdl_haptic\n"
        "assert 'sdl2' not in sys.modules, 'sdl2 imported eagerly'\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
