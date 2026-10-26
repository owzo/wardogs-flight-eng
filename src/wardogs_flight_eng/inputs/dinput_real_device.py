"""Device calls of the real DirectInput adapter: ``IDirectInputDevice8W``.

``DeviceHandle`` is the adapter's ``DiDeviceHandle``: the device pointer
(None once released), its axis objects and the effects created on it.
``device_call`` returns the raw ``HRESULT``, or ``DIERR_NOTINITIALIZED`` on
a released device without touching COM.
"""

from ctypes import POINTER, byref, c_int, c_uint32, c_void_p, sizeof
from dataclasses import dataclass, field
from typing import Any

from wardogs_flight_eng.inputs.dinput_api import (
    DIJOFS_BY_INDEX,
    DiAxisInfo,
    DInputError,
    DiState,
    EffectKind,
)
from wardogs_flight_eng.inputs.dinput_com import FUNCTYPE, com_call, method, release
from wardogs_flight_eng.inputs.dinput_format import property_dword, property_range
from wardogs_flight_eng.inputs.dinput_guids import (
    AXIS_RANGE,
    DEVICE8_SLOTS,
    DIDFT_AXIS,
    DIDOI_FFACTUATOR,
    DIEFT_ALL,
    DIENUM_CONTINUE,
    DIERR_NOTINITIALIZED,
    DIPH_BYOFFSET,
    DIPH_DEVICE,
    DIPROP_RANGE,
    EFFECT_KIND_BY_GUID,
)
from wardogs_flight_eng.inputs.dinput_real_effects import EffectHandle, release_effect
from wardogs_flight_eng.inputs.dinput_structs import (
    DIDATAFORMAT,
    DIDEVICEOBJECTINSTANCEW,
    DIEFFECTINFOW,
    DIJOYSTATE2,
    guid_text,
)

ENUM_OBJECTS_CALLBACK = FUNCTYPE(c_int, POINTER(DIDEVICEOBJECTINSTANCEW), c_void_p)
ENUM_EFFECTS_CALLBACK = FUNCTYPE(c_int, POINTER(DIEFFECTINFOW), c_void_p)

_SIGNATURES: dict[str, tuple[Any, ...]] = {
    "EnumObjects": (ENUM_OBJECTS_CALLBACK, c_void_p, c_uint32),
    "GetProperty": (c_void_p, c_void_p),
    "SetProperty": (c_void_p, c_void_p),
    "Acquire": (),
    "Unacquire": (),
    "GetDeviceState": (c_uint32, c_void_p),
    "SetDataFormat": (c_void_p,),
    "SetCooperativeLevel": (c_void_p, c_uint32),
    "EnumEffects": (ENUM_EFFECTS_CALLBACK, c_void_p, c_uint32),
    "SendForceFeedbackCommand": (c_uint32,),
    "Poll": (),
}
IDLE_STATE = DiState((0,) * len(DIJOFS_BY_INDEX), (False,) * 128)
_METHODS = {
    name: method(DEVICE8_SLOTS[name], *args) for name, args in _SIGNATURES.items()
}


@dataclass(eq=False)
class DeviceHandle:
    """One ``IDirectInputDevice8W``; ``ptr`` is None once released."""

    ptr: int | None
    axes: list[DiAxisInfo] = field(default_factory=list)
    effects: list[EffectHandle] = field(default_factory=list)


def device_call(device: DeviceHandle, name: str, *args: Any) -> int:
    """Call the device method ``name``; its ``HRESULT``."""
    if device.ptr is None:
        return DIERR_NOTINITIALIZED
    return com_call(device.ptr, _METHODS[name], *args)


def _fail(call: str, status: int) -> DInputError:
    return DInputError(f"{call} failed: {status & 0xFFFFFFFF:#010x}")


def enum_axes(device: DeviceHandle) -> list[DiAxisInfo]:
    """``EnumObjects(DIDFT_AXIS)`` in ``dwOfs`` order (after ``SetDataFormat``)."""
    found: list[DiAxisInfo] = []

    def collect(instance: Any, _context: Any) -> int:
        item = instance.contents
        actuator = bool(item.dwFlags & DIDOI_FFACTUATOR)
        found.append(DiAxisInfo(int(item.dwOfs), str(item.tszName), actuator))
        return DIENUM_CONTINUE

    callback = ENUM_OBJECTS_CALLBACK(collect)
    status = device_call(device, "EnumObjects", callback, None, DIDFT_AXIS)
    if status < 0:
        raise _fail("EnumObjects", status)
    return sorted(found, key=lambda axis: axis.offset)


def set_axis_range(device: DeviceHandle) -> None:
    """``DIPROP_RANGE`` 0..65535 on every axis, as ``DiState`` documents.

    Set device-wide first; a device that refuses that gets it per readable
    axis object (``DIPH_BYOFFSET``), and a refusal there is a ``DInputError``.
    """
    low, high = AXIS_RANGE
    whole = property_range(DIPH_DEVICE, 0, low, high)
    if device_call(device, "SetProperty", DIPROP_RANGE, byref(whole)) >= 0:
        return
    for axis in device.axes:
        if axis.offset not in DIJOFS_BY_INDEX:
            continue
        one = property_range(DIPH_BYOFFSET, axis.offset, low, high)
        status = device_call(device, "SetProperty", DIPROP_RANGE, byref(one))
        if status < 0:
            raise _fail(f"DIPROP_RANGE on {axis.name!r}", status)


def enum_effect_guids(device: DeviceHandle) -> list[str]:
    """``EnumEffects(DIEFT_ALL)``: each supported effect's GUID text."""
    found: list[str] = []

    def collect(info: Any, _context: Any) -> int:
        found.append(guid_text(info.contents.guid))
        return DIENUM_CONTINUE

    callback = ENUM_EFFECTS_CALLBACK(collect)
    status = device_call(device, "EnumEffects", callback, None, DIEFT_ALL)
    if status < 0:
        raise _fail("EnumEffects", status)
    return found


def configure(device: DeviceHandle, data_format: DIDATAFORMAT) -> None:
    """``SetDataFormat``, then learn the axis objects and set their range."""
    status = device_call(device, "SetDataFormat", byref(data_format))
    if status < 0:
        raise _fail("SetDataFormat", status)
    device.axes = enum_axes(device)
    set_axis_range(device)


def set_dword(device: DeviceHandle, prop: int, value: int) -> int:
    """``SetProperty`` of a device-wide ``DIPROPDWORD`` (``prop`` = ``DIPROP_*``)."""
    block = property_dword(DIPH_DEVICE, 0, value)
    return device_call(device, "SetProperty", prop, byref(block))


def get_dword(device: DeviceHandle, prop: int) -> tuple[int, int]:
    """``GetProperty`` of a device-wide ``DIPROPDWORD``: (status, value)."""
    block = property_dword(DIPH_DEVICE, 0)
    status = device_call(device, "GetProperty", prop, byref(block))
    return status, int(block.dwData)


def as_device(dev: object) -> DeviceHandle:
    """``dev`` as this adapter's handle; anything else is a ``TypeError``."""
    if not isinstance(dev, DeviceHandle):
        raise TypeError(f"not a DirectInput device handle: {dev!r}")
    return dev


def effect_kinds(device: DeviceHandle) -> frozenset[EffectKind]:
    """The six known effect kinds among the device's ``EnumEffects`` GUIDs."""
    guids = enum_effect_guids(device)
    return frozenset(EFFECT_KIND_BY_GUID[g] for g in guids if g in EFFECT_KIND_BY_GUID)


def read_state(device: DeviceHandle) -> tuple[int, DiState]:
    """``Poll`` (``DI_NOEFFECT`` is a success), then ``GetDeviceState``; a
    failing status comes with an all-zero state."""
    status = device_call(device, "Poll")
    if status < 0:
        return status, IDLE_STATE
    state = DIJOYSTATE2()
    status = device_call(device, "GetDeviceState", sizeof(state), byref(state))
    if status < 0:
        return status, IDLE_STATE
    buttons = tuple(b & 0x80 != 0 for b in state.rgbButtons)
    return status, DiState(state.axis_values(), buttons)


def release_device(device: DeviceHandle) -> None:
    """Release the device's remaining effects, then the device; idempotent."""
    for handle in device.effects:
        release_effect(handle)
    device.effects.clear()
    if device.ptr is not None:
        ptr, device.ptr = device.ptr, None
        release(ptr, "device")
