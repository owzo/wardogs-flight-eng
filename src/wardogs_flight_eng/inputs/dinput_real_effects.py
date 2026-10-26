"""Effect calls of the real DirectInput adapter.

``create`` is ``IDirectInputDevice8W::CreateEffect``; the rest are
``IDirectInputEffect`` methods on the handle it returns. Every call returns
the raw ``HRESULT``; one on a released handle returns
``DIERR_NOTINITIALIZED`` without touching COM. ``set_parameters`` never sets
``DIEP_START``: ``start`` is the only call that starts an effect.
"""

from ctypes import POINTER, byref, c_uint32, c_void_p

from wardogs_flight_eng.inputs.dinput_api import DiEffect
from wardogs_flight_eng.inputs.dinput_com import com_call, method, release
from wardogs_flight_eng.inputs.dinput_format import EffectStruct, parameter_flags
from wardogs_flight_eng.inputs.dinput_guids import (
    DEVICE8_SLOTS,
    DIERR_NOTINITIALIZED,
    EFFECT_GUIDS,
    EFFECT_SLOTS,
)
from wardogs_flight_eng.inputs.dinput_structs import guid_from_text

_CREATE_EFFECT = method(
    DEVICE8_SLOTS["CreateEffect"], c_void_p, c_void_p, POINTER(c_void_p), c_void_p
)
_SET_PARAMETERS = method(EFFECT_SLOTS["SetParameters"], c_void_p, c_uint32)
_START = method(EFFECT_SLOTS["Start"], c_uint32, c_uint32)
_STOP = method(EFFECT_SLOTS["Stop"])


class EffectHandle:
    """One ``IDirectInputEffect`` and the ``DIEFFECT`` buffers last sent to it.

    ``ptr`` is None once released.
    """

    def __init__(self, ptr: int, block: EffectStruct) -> None:
        self.ptr: int | None = ptr
        self.block = block


def create(device: int, effect: DiEffect) -> tuple[int, EffectHandle | None]:
    """``CreateEffect`` on the device pointer; the handle is None on failure."""
    block = EffectStruct(effect)
    guid = guid_from_text(EFFECT_GUIDS[effect.kind])
    out = c_void_p()
    status = com_call(
        device, _CREATE_EFFECT, byref(guid), byref(block.struct), byref(out), None
    )
    if status < 0 or not out.value:
        return status, None
    return status, EffectHandle(out.value, block)


def set_parameters(handle: EffectHandle, effect: DiEffect, norestart: bool) -> int:
    """``SetParameters`` with every parameter ``DiEffect`` carries."""
    if handle.ptr is None:
        return DIERR_NOTINITIALIZED
    block = EffectStruct(effect)
    flags = parameter_flags(effect, norestart)
    status = com_call(handle.ptr, _SET_PARAMETERS, byref(block.struct), flags)
    handle.block = block
    return status


def start(handle: EffectHandle) -> int:
    """``Start(1, 0)``: one iteration, other effects untouched."""
    if handle.ptr is None:
        return DIERR_NOTINITIALIZED
    return com_call(handle.ptr, _START, 1, 0)


def stop(handle: EffectHandle) -> int:
    if handle.ptr is None:
        return DIERR_NOTINITIALIZED
    return com_call(handle.ptr, _STOP)


def release_effect(handle: EffectHandle) -> None:
    """``Release``; idempotent, and never raises."""
    if handle.ptr is None:
        return
    ptr, handle.ptr = handle.ptr, None
    release(ptr, "effect")
