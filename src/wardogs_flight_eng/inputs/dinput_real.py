"""The real ``DirectInputApi``: DirectInput 8 through ctypes COM calls.

``shared()`` builds the adapter on first use (never at import): it loads
``dinput8.dll``, creates the hidden window and calls ``DirectInput8Create``.
Device handles are ``DeviceHandle`` objects holding the device pointer, its
axis objects and the effects created on it. Calls return the raw
``HRESULT``; one on a released device or effect returns
``DIERR_NOTINITIALIZED``. ``open_device`` raises ``DInputError`` only when
``CreateDevice``, ``SetDataFormat``, the axis enumeration or the 0..65535
axis range fails; ``enumerate_devices`` and ``enum_effect_kinds`` raise it
when the enumeration itself fails. ``release_effect``, ``release_device``
and ``close`` are idempotent and never raise.
"""

import logging

from wardogs_flight_eng.inputs import dinput_api as api
from wardogs_flight_eng.inputs import dinput_real_effects as effects
from wardogs_flight_eng.inputs import dinput_real_root as root
from wardogs_flight_eng.inputs.dinput_api import (
    DiAxisInfo,
    DiDeviceInfo,
    DiEffect,
    DiGuid,
    DInputError,
    DiState,
    EffectKind,
)
from wardogs_flight_eng.inputs.dinput_com import (
    create_window,
    destroy_window,
    release,
    win32,
)
from wardogs_flight_eng.inputs.dinput_format import JoystickFormat
from wardogs_flight_eng.inputs.dinput_guids import (
    DIERR_NOTINITIALIZED,
    DIPROP_AUTOCENTER,
    DIPROP_FFGAIN,
    DIPROPAUTOCENTER_OFF,
    DISCL_BACKGROUND,
    DISCL_EXCLUSIVE,
)
from wardogs_flight_eng.inputs.dinput_real_device import (
    DeviceHandle,
    as_device,
    configure,
    device_call,
    effect_kinds,
    get_dword,
    read_state,
    release_device,
    set_dword,
)

log = logging.getLogger(__name__)


def _effect(handle: object) -> effects.EffectHandle:
    if not isinstance(handle, effects.EffectHandle):
        raise TypeError(f"not a DirectInput effect handle: {handle!r}")
    return handle


class RealDirectInput:
    """``DirectInputApi`` over ``IDirectInput8W`` and a hidden window."""

    DISFFC_RESET = api.DISFFC_RESET
    DISFFC_STOPALL = api.DISFFC_STOPALL
    DISFFC_SETACTUATORSON = api.DISFFC_SETACTUATORSON

    def __init__(self) -> None:
        self._win32 = win32()
        hinstance, hwnd = create_window(self._win32)
        self._hwnd: int | None = hwnd
        try:
            self._di: int | None = root.directinput8_create(self._win32, hinstance)
        except BaseException:
            destroy_window(self._win32, hwnd)
            raise
        self._format = JoystickFormat()
        self._devices: list[DeviceHandle] = []

    @property
    def closed(self) -> bool:
        return self._di is None

    def _live(self) -> int:
        if self._di is None:
            raise DInputError("the DirectInput adapter is closed")
        return self._di

    def enumerate_devices(self) -> list[DiDeviceInfo]:
        return root.enumerate_devices(self._live())

    def open_device(self, instance_guid: DiGuid) -> object:
        device = DeviceHandle(root.create_device(self._live(), instance_guid))
        self._devices.append(device)
        try:
            configure(device, self._format.format)
        except BaseException:
            self.release_device(device)
            raise
        return device

    def axes(self, dev: object) -> list[DiAxisInfo]:
        return list(as_device(dev).axes)

    def set_cooperative_exclusive_background(self, dev: object) -> int:
        level = DISCL_EXCLUSIVE | DISCL_BACKGROUND
        return device_call(as_device(dev), "SetCooperativeLevel", self._hwnd, level)

    def set_autocenter_off(self, dev: object) -> int:
        return set_dword(as_device(dev), DIPROP_AUTOCENTER, DIPROPAUTOCENTER_OFF)

    def set_ff_gain(self, dev: object, gain: int) -> int:
        return set_dword(as_device(dev), DIPROP_FFGAIN, gain)

    def get_ff_gain(self, dev: object) -> int:
        """The device gain 0..10000, or the failing ``HRESULT`` (negative)."""
        status, gain = get_dword(as_device(dev), DIPROP_FFGAIN)
        if status < 0:
            log.warning("DIPROP_FFGAIN read failed: %#010x", status & 0xFFFFFFFF)
            return status
        return gain

    def acquire(self, dev: object) -> int:
        return device_call(as_device(dev), "Acquire")

    def unacquire(self, dev: object) -> int:
        return device_call(as_device(dev), "Unacquire")

    def ff_command(self, dev: object, command: int) -> int:
        return device_call(as_device(dev), "SendForceFeedbackCommand", command)

    def enum_effect_kinds(self, dev: object) -> frozenset[EffectKind]:
        return effect_kinds(as_device(dev))

    def poll_state(self, dev: object) -> tuple[int, DiState]:
        return read_state(as_device(dev))

    def create_effect(self, dev: object, effect: DiEffect) -> tuple[int, object]:
        device = as_device(dev)
        if device.ptr is None:
            return DIERR_NOTINITIALIZED, None
        status, handle = effects.create(device.ptr, effect)
        if handle is not None:
            device.effects.append(handle)
        return status, handle

    def set_parameters(
        self, effect_handle: object, effect: DiEffect, norestart: bool
    ) -> int:
        return effects.set_parameters(_effect(effect_handle), effect, norestart)

    def start(self, effect_handle: object) -> int:
        return effects.start(_effect(effect_handle))

    def stop(self, effect_handle: object) -> int:
        return effects.stop(_effect(effect_handle))

    def release_effect(self, effect_handle: object) -> None:
        handle = _effect(effect_handle)
        effects.release_effect(handle)
        for device in self._devices:
            if handle in device.effects:
                device.effects.remove(handle)

    def release_device(self, dev: object) -> None:
        device = as_device(dev)
        if device in self._devices:
            self._devices.remove(device)
        release_device(device)

    def close(self) -> None:
        """Release every device, then DirectInput; destroy the window."""
        for device in list(self._devices):
            self.release_device(device)
        if self._di is not None:
            di, self._di = self._di, None
            release(di, "IDirectInput8")
        if self._hwnd is not None:
            hwnd, self._hwnd = self._hwnd, None
            destroy_window(self._win32, hwnd)


_shared: RealDirectInput | None = None


def shared() -> RealDirectInput:
    """The process's adapter, built on the first call and again after ``close``."""
    global _shared
    if _shared is None or _shared.closed:
        _shared = RealDirectInput()
    return _shared
