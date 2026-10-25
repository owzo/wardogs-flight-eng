"""DirectInput base as an input device: open sequence, reads, loss, close."""

import pytest
from dinput_support import FakeDiDevice, FakeDirectInput, ab9

from wardogs_flight_eng.inputs import dinput_api as di
from wardogs_flight_eng.inputs.dinput_api import DiAxisInfo, DInputError, DiState
from wardogs_flight_eng.inputs.dinput_device import (
    DInputJoystick,
    ff_actuator_check,
    open_dinput_joystick,
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
LVX = 176  # DIJOYSTATE2.lVX: an axis object outside the eight state slots


def _le16(value: int) -> str:
    return f"{value & 0xFF:02x}{value >> 8:02x}"


def sdl_guid(device: FakeDiDevice) -> str:
    """The Windows SDL GUID layout: bus, crc, LE vendor, 0, LE product, 0, ..."""
    return f"0300ab9c{_le16(device.vid)}0000{_le16(device.pid)}000000000000"


def _opened(device: FakeDiDevice) -> tuple[FakeDirectInput, DInputJoystick]:
    fake = FakeDirectInput(device)
    return fake, open_dinput_joystick(fake, sdl_guid(device))


def _set_axis(device: FakeDiDevice, slot: int, raw: int) -> None:
    axes = list(device.state.axes)
    axes[slot] = raw
    device.state = DiState(tuple(axes), device.state.buttons)


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


def test_axis_objects_outside_the_state_are_not_counted() -> None:
    base = ab9()
    velocity = DiAxisInfo(LVX, "X Velocity", False)
    base.axes = [velocity, *base.axes, DiAxisInfo(24, "Slider", False)]
    _, joystick = _opened(base)
    assert [a.offset for a in joystick.axes_info] == [0, 4, 8, 20, 24]
    assert joystick.unreadable_axes == [velocity]
    assert joystick.axis_count == 5
    _set_axis(base, 6, 65535)
    joystick.poll()
    readings = [joystick.axis(i) for i in range(joystick.axis_count)]
    assert readings[4] == 1.0
    assert readings[:4] == pytest.approx([0.0] * 4, abs=1e-4)


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


def test_interrupt_after_acquire_still_releases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = ab9()
    fake = FakeDirectInput(base)

    def interrupted(dev: object, command: int) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(fake, "ff_command", interrupted)
    with pytest.raises(KeyboardInterrupt):
        open_dinput_joystick(fake, sdl_guid(base))
    assert fake.names()[-2:] == ["acquire", "release_device"]


@pytest.mark.parametrize("failure", ["detached", "unacquire"])
def test_close_unacquires_releases_once_and_stays_quiet(failure: str) -> None:
    base = ab9()
    fake, joystick = _opened(base)
    if failure == "detached":
        base.attached = False
    else:
        fake.fail["unacquire"] = di.DIERR_NOTACQUIRED
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
