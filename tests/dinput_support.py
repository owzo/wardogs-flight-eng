"""A fake DirectInput 8 for the dinput tests: records the calls it gets.

``FakeDirectInput`` implements ``DirectInputApi`` over ``FakeDiDevice`` objects.
A status call returns ``fail[name]`` when set. On a detached device every
device call returns ``lost_code`` (default ``DIERR_INPUTLOST``) and changes
nothing, except teardown (``unacquire``, ``release_effect``,
``release_device``, ``close``), which succeeds as the real calls do.
``poll_state`` before ``acquire`` is ``DIERR_NOTACQUIRED``; ``ff_command``
with anything but one ``DISFFC_*`` command is ``DIERR_INVALIDPARAM``.
``calls`` skips the queries (``enumerate_devices``, ``axes``,
``enum_effect_kinds``, ``get_ff_gain``), omits device handles (open/release
record the instance GUID) and shows effect handles as their id.
"""

from dataclasses import dataclass

from dinput_fake_effects import FakeEffectCalls

from wardogs_flight_eng.inputs import dinput_api as di
from wardogs_flight_eng.inputs.dinput_api import (
    DiAxisInfo,
    DiDeviceInfo,
    DiGuid,
    DInputError,
    DiState,
    EffectKind,
)

# Placeholder ids for tests only: not read from a real AB9.
PLACEHOLDER_AB9_VID = 0x346E
PLACEHOLDER_AB9_PID = 0x0010
CENTRE = 32767
_COMMANDS = (di.DISFFC_RESET, di.DISFFC_STOPALL, di.DISFFC_SETACTUATORSON)


@dataclass
class FakeDiDevice:
    vid: int
    pid: int
    instance_name: str
    product_name: str
    force_feedback: bool
    axes: list[DiAxisInfo]
    kinds: frozenset[EffectKind]
    state: DiState
    attached: bool = True
    instance_guid: DiGuid = ""
    acquired: bool = False
    exclusive: bool = False
    autocenter: bool = True
    gain: int = 10000
    actuators_on: bool = False

    def info(self) -> DiDeviceInfo:
        data1 = (self.pid << 16) | self.vid
        product = f"{{{data1:08X}-0000-0000-0000-504944564944}}"
        return DiDeviceInfo(
            self.instance_guid,
            product,
            self.vid,
            self.pid,
            self.instance_name,
            self.product_name,
            self.force_feedback,
        )


def ab9() -> FakeDiDevice:
    """A force-feedback base: X/Y/Z/Rz with actuators on X and Y, all kinds."""
    axes = [
        DiAxisInfo(0, "X Axis", True),
        DiAxisInfo(4, "Y Axis", True),
        DiAxisInfo(8, "Z Axis", False),
        DiAxisInfo(20, "Z Rotation", False),
    ]
    state = DiState((CENTRE,) * len(di.DIJOFS_BY_INDEX), (False,) * 128)
    return FakeDiDevice(
        PLACEHOLDER_AB9_VID,
        PLACEHOLDER_AB9_PID,
        "MOZA AB9 Base",
        "MOZA AB9 FFB Base",
        True,
        axes,
        frozenset(di.EFFECT_KINDS),
        state,
    )


def _device(handle: object) -> FakeDiDevice:
    assert isinstance(handle, FakeDiDevice)
    return handle


class FakeDirectInput(FakeEffectCalls):
    """In-memory ``DirectInputApi``; constants carry the dinput.h values."""

    DISFFC_RESET = di.DISFFC_RESET
    DISFFC_STOPALL = di.DISFFC_STOPALL
    DISFFC_SETACTUATORSON = di.DISFFC_SETACTUATORSON

    def __init__(self, *devices: FakeDiDevice) -> None:
        super().__init__()
        self.devices = list(devices)
        for index, device in enumerate(self.devices, start=1):
            if not device.instance_guid:
                device.instance_guid = f"{{{index:08X}-0000-11F0-8001-444553540000}}"
        self.closed = False

    def _owner(self, dev: object) -> FakeDiDevice:
        return _device(dev)

    def enumerate_devices(self) -> list[DiDeviceInfo]:
        return [device.info() for device in self.devices if device.attached]

    def open_device(self, instance_guid: DiGuid) -> object:
        self.calls.append(("open_device", (instance_guid,)))
        if "open_device" in self.fail:
            code = self.fail["open_device"] & 0xFFFFFFFF
            raise DInputError(f"CreateDevice failed: {code:#010x}")
        for device in self.devices:
            if device.instance_guid == instance_guid and device.attached:
                return device
        raise DInputError(f"CreateDevice: no device {instance_guid}")

    def axes(self, dev: object) -> list[DiAxisInfo]:
        return list(_device(dev).axes)

    def set_cooperative_exclusive_background(self, dev: object) -> int:
        device = _device(dev)
        status = self._status("set_cooperative_exclusive_background", (), device)
        if status >= 0:
            device.exclusive = True
        return status

    def set_autocenter_off(self, dev: object) -> int:
        device = _device(dev)
        status = self._status("set_autocenter_off", (), device)
        if status >= 0:
            device.autocenter = False
        return status

    def set_ff_gain(self, dev: object, gain: int) -> int:
        device = _device(dev)
        status = self._status("set_ff_gain", (gain,), device)
        if status >= 0:
            device.gain = gain
        return status

    def get_ff_gain(self, dev: object) -> int:
        return _device(dev).gain

    def acquire(self, dev: object) -> int:
        device = _device(dev)
        status = self._status("acquire", (), device)
        if status >= 0:
            device.acquired = True
        return status

    def unacquire(self, dev: object) -> int:
        status = self._status("unacquire", ())
        if status >= 0:
            _device(dev).acquired = False
        return status

    def ff_command(self, dev: object, command: int) -> int:
        device = _device(dev)
        status = self._status("ff_command", (command,), device)
        if status < 0:
            return status
        if command not in _COMMANDS:
            return di.DIERR_INVALIDPARAM
        if command == di.DISFFC_RESET:
            self._reset_owned(device)
        elif command == di.DISFFC_STOPALL:
            self._stop_owned(device)
        else:
            device.actuators_on = True
        return status

    def enum_effect_kinds(self, dev: object) -> frozenset[EffectKind]:
        return _device(dev).kinds

    def poll_state(self, dev: object) -> tuple[int, DiState]:
        device = _device(dev)
        status = self._status("poll_state", (), device)
        if status >= 0 and not device.acquired:
            status = di.DIERR_NOTACQUIRED
        return status, device.state

    def release_device(self, dev: object) -> None:
        device = _device(dev)
        self.calls.append(("release_device", (device.instance_guid,)))
        device.acquired = False

    def close(self) -> None:
        self.calls.append(("close", ()))
        self.closed = True
