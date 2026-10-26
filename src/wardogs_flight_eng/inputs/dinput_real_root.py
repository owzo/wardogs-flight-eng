"""``IDirectInput8W`` calls of the real adapter: create, enumerate, open.

Each raises ``DInputError`` on a failing ``HRESULT``: the root object and
device creation have no status to hand back through the seam.
"""

from ctypes import POINTER, byref, c_int, c_uint32, c_void_p
from typing import Any

from wardogs_flight_eng.inputs.dinput_api import DiDeviceInfo, DiGuid, DInputError
from wardogs_flight_eng.inputs.dinput_com import FUNCTYPE, Win32, com_call, method
from wardogs_flight_eng.inputs.dinput_guids import (
    DI8DEVCLASS_GAMECTRL,
    DIEDFL_ATTACHEDONLY,
    DIEDFL_FORCEFEEDBACK,
    DIENUM_CONTINUE,
    DIRECTINPUT8_SLOTS,
    DIRECTINPUT_VERSION,
    IID_IDIRECTINPUT8W,
)
from wardogs_flight_eng.inputs.dinput_structs import (
    DIDEVICEINSTANCEW,
    guid_from_text,
    guid_text,
)

ENUM_DEVICES_CALLBACK = FUNCTYPE(c_int, POINTER(DIDEVICEINSTANCEW), c_void_p)
_CREATE_DEVICE = method(
    DIRECTINPUT8_SLOTS["CreateDevice"], c_void_p, POINTER(c_void_p), c_void_p
)
_ENUM_DEVICES = method(
    DIRECTINPUT8_SLOTS["EnumDevices"],
    c_uint32,
    ENUM_DEVICES_CALLBACK,
    c_void_p,
    c_uint32,
)


def _failed(call: str, status: int) -> DInputError:
    return DInputError(f"{call} failed: {status & 0xFFFFFFFF:#010x}")


def directinput8_create(api: Win32, hinstance: int) -> int:
    """``DirectInput8Create`` for ``IDirectInput8W``; the interface pointer."""
    iid, out = guid_from_text(IID_IDIRECTINPUT8W), c_void_p()
    status = int(
        api.call(
            "DirectInput8Create",
            hinstance,
            DIRECTINPUT_VERSION,
            byref(iid),
            byref(out),
            None,
        )
    )
    if status < 0 or not out.value:
        raise _failed("DirectInput8Create", status)
    return out.value


def _enumerate(di: int, flags: int) -> list[DIDEVICEINSTANCEW]:
    found: list[DIDEVICEINSTANCEW] = []

    def collect(instance: Any, _context: Any) -> int:
        found.append(DIDEVICEINSTANCEW.from_buffer_copy(instance.contents))
        return DIENUM_CONTINUE

    callback = ENUM_DEVICES_CALLBACK(collect)
    status = com_call(di, _ENUM_DEVICES, DI8DEVCLASS_GAMECTRL, callback, None, flags)
    if status < 0:
        raise _failed("EnumDevices", status)
    return found


def _info(found: DIDEVICEINSTANCEW, force_feedback: bool) -> DiDeviceInfo:
    data1 = int(found.guidProduct.Data1)  # (PID << 16) | VID
    return DiDeviceInfo(
        guid_text(found.guidInstance),
        guid_text(found.guidProduct),
        data1 & 0xFFFF,
        data1 >> 16,
        str(found.tszInstanceName),
        str(found.tszProductName),
        force_feedback,
    )


def enumerate_devices(di: int) -> list[DiDeviceInfo]:
    """Attached game controllers; force feedback from a filtered second pass."""
    attached = _enumerate(di, DIEDFL_ATTACHEDONLY)
    forced = _enumerate(di, DIEDFL_ATTACHEDONLY | DIEDFL_FORCEFEEDBACK)
    ff = {guid_text(found.guidInstance) for found in forced}
    return [_info(found, guid_text(found.guidInstance) in ff) for found in attached]


def create_device(di: int, instance_guid: DiGuid) -> int:
    """``CreateDevice``: the new ``IDirectInputDevice8W`` pointer."""
    guid, out = guid_from_text(instance_guid), c_void_p()
    status = com_call(di, _CREATE_DEVICE, byref(guid), byref(out), None)
    if status < 0 or not out.value:
        raise _failed(f"CreateDevice {instance_guid}", status)
    return out.value
