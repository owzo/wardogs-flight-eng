"""DirectInput base as an input device: GUID matching, open sequence, reads."""

import dataclasses

import pytest
from dinput_support import FakeDiDevice, FakeDirectInput, ab9

from wardogs_flight_eng.inputs import dinput_api as di
from wardogs_flight_eng.inputs.dinput_api import DiAxisInfo, DInputError, DiState
from wardogs_flight_eng.inputs.dinput_device import (
    DInputJoystick,
    ff_actuator_check,
    match_sdl_guid,
    open_dinput_joystick,
    vid_pid_from_sdl_guid,
)
from wardogs_flight_eng.inputs.protocol import (
    DeviceLostError,
    InputConfigError,
    InputDevice,
)
from wardogs_flight_eng.outputs.haptic_axes import HapticAxis, HapticAxisMap

OPEN_ORDER = [
    "open_device",
    "set_cooperative_exclusive_background",
    "set_autocenter_off",
    "set_ff_gain",
    "acquire",
    "ff_command",
    "ff_command",
]


def _le16(value: int) -> str:
    return f"{value & 0xFF:02x}{value >> 8:02x}"


def sdl_guid(device: FakeDiDevice) -> str:
    """The Windows SDL GUID layout: bus, crc, LE vendor, 0, LE product, 0, ..."""
    return f"0300ab9c{_le16(device.vid)}0000{_le16(device.pid)}000000000000"


def _second(device: FakeDiDevice, name: str, ff: bool = True) -> FakeDiDevice:
    return dataclasses.replace(device, instance_name=name, force_feedback=ff)


def _opened(device: FakeDiDevice) -> tuple[FakeDirectInput, DInputJoystick]:
    fake = FakeDirectInput(device)
    return fake, open_dinput_joystick(fake, sdl_guid(device))


def _set_axis(device: FakeDiDevice, slot: int, raw: int) -> None:
    axes = list(device.state.axes)
    axes[slot] = raw
    device.state = DiState(tuple(axes), device.state.buttons)


def test_vid_pid_come_from_the_little_endian_words() -> None:
    base = ab9()
    assert sdl_guid(base) == "0300ab9c6e3400001000000000000000"
    assert vid_pid_from_sdl_guid(sdl_guid(base).upper()) == (0x346E, 0x0010)


@pytest.mark.parametrize("bad", ["", "0300ab9c6e34", "z" * 32, "0" * 33])
def test_malformed_sdl_guid_is_a_config_error(bad: str) -> None:
    with pytest.raises(InputConfigError, match="SDL GUID"):
        vid_pid_from_sdl_guid(bad)


def test_match_prefers_the_force_feedback_instance() -> None:
    plain = _second(ab9(), "AB9 HID only", ff=False)
    fake = FakeDirectInput(plain, ab9())
    found = match_sdl_guid(sdl_guid(plain), fake.enumerate_devices())
    assert found.instance_name == "MOZA AB9 Base"
    assert found.force_feedback


def test_two_force_feedback_instances_are_ambiguous() -> None:
    fake = FakeDirectInput(ab9(), _second(ab9(), "MOZA AB9 Base #2"))
    with pytest.raises(InputConfigError) as raised:
        match_sdl_guid(sdl_guid(ab9()), fake.enumerate_devices())
    assert "'MOZA AB9 Base', 'MOZA AB9 Base #2'" in str(raised.value)


def test_no_matching_device_is_device_lost() -> None:
    with pytest.raises(DeviceLostError, match="346e:0010"):
        match_sdl_guid(sdl_guid(ab9()), FakeDirectInput().enumerate_devices())


def test_open_runs_the_sequence_in_order() -> None:
    base = ab9()
    base.axes = list(reversed(base.axes))
    fake, joystick = _opened(base)
    assert fake.names() == [*OPEN_ORDER, "poll_state"]
    assert fake.args("set_ff_gain") == [(10000,)]
    assert fake.args("ff_command") == [(di.DISFFC_RESET,), (di.DISFFC_SETACTUATORSON,)]
    assert (base.exclusive, base.autocenter, base.acquired) == (True, False, True)
    assert base.actuators_on
    device: InputDevice = joystick
    assert (device.name, device.guid) == ("MOZA AB9 Base", sdl_guid(base))
    assert (device.axis_count, device.button_count, device.alive) == (4, 128, True)
    assert joystick.handle is base and joystick.api is fake
    assert [a.offset for a in joystick.axes_info] == [0, 4, 8, 20]


def test_axis_and_button_read_the_last_poll() -> None:
    base = ab9()
    _, joystick = _opened(base)
    _set_axis(base, 0, 65535)
    _set_axis(base, 5, 0)
    base.state = DiState(base.state.axes, (False, True) + (False,) * 126)
    joystick.poll()
    assert (joystick.axis(0), joystick.axis(3)) == (1.0, -1.0)
    assert joystick.axis(1) == pytest.approx(0.0, abs=1e-4)
    assert (joystick.button(0), joystick.button(1)) == (False, True)
    _set_axis(base, 0, 0)
    joystick.poll()
    assert joystick.axis(0) == -1.0


def test_axis_outside_the_state_layout_is_a_config_error() -> None:
    base = ab9()
    base.axes = [*base.axes, DiAxisInfo(32, "X Velocity", False)]
    _, joystick = _opened(base)
    with pytest.raises(InputConfigError, match="X Velocity"):
        joystick.axis(4)


def test_detached_device_poll_is_device_lost() -> None:
    base = ab9()
    _, joystick = _opened(base)
    base.attached = False
    with pytest.raises(DeviceLostError):
        joystick.poll()
    assert not joystick.alive


def test_other_poll_failure_is_dinput_error() -> None:
    fake, joystick = _opened(ab9())
    fake.fail["poll_state"] = di.DIERR_INVALIDPARAM
    with pytest.raises(DInputError, match="poll_state"):
        joystick.poll()
    assert joystick.alive


@pytest.mark.parametrize(
    ("call", "code", "error"),
    [
        ("acquire", di.DIERR_INVALIDPARAM, DInputError),
        ("set_autocenter_off", di.DIERR_INVALIDPARAM, DInputError),
        ("ff_command", di.DIERR_UNPLUGGED, DeviceLostError),
        ("poll_state", di.DIERR_INPUTLOST, DeviceLostError),
    ],
)
def test_failed_open_step_raises_and_releases(
    call: str, code: int, error: type[Exception]
) -> None:
    base = ab9()
    fake = FakeDirectInput(base)
    fake.fail[call] = code
    with pytest.raises(error, match=call):
        open_dinput_joystick(fake, sdl_guid(base))
    assert fake.names()[-2:] == [call, "release_device"]


def test_close_unacquires_releases_once_even_when_lost() -> None:
    base = ab9()
    fake, joystick = _opened(base)
    base.attached = False
    joystick.close()
    joystick.close()
    assert fake.names()[-2:] == ["unacquire", "release_device"]
    assert fake.count("release_device") == 1
    assert not joystick.alive
    joystick.poll()
    assert joystick.axis(0) == 0.0 and not joystick.button(0)


@pytest.mark.parametrize(
    ("axis_count", "pitch", "roll", "named"),
    [(4, 1, 2, ("roll", "axis 2", "Z Axis")), (2, 2, 0, ("pitch", "axis 2"))],
)
def test_actuator_check_rejects_a_non_actuator_axis(
    axis_count: int, pitch: int, roll: int, named: tuple[str, ...]
) -> None:
    base = ab9()
    base.axes = base.axes[:axis_count]
    _, joystick = _opened(base)
    axis_map = HapticAxisMap(HapticAxis(pitch, 1.0), HapticAxis(roll, 1.0))
    with pytest.raises(InputConfigError) as raised:
        ff_actuator_check(joystick, axis_map)
    assert all(part in str(raised.value) for part in named)


def test_actuator_check_accepts_x_and_y() -> None:
    _, joystick = _opened(ab9())
    ff_actuator_check(joystick, HapticAxisMap(HapticAxis(1, 1.0), HapticAxis(0, 1.0)))
