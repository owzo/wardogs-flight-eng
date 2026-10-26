"""Values the adapter builds from the dinput.h structs.

``JoystickFormat`` is ``c_dfDIJoystick2`` built by hand (the original is
import-library data, not a ``dinput8.dll`` export); ``EffectStruct`` turns a
``DiEffect`` mirror into a genuine ``DIEFFECT``; ``property_*`` build the
property blocks. Each object owns every buffer its struct points into, so the
struct stays valid for as long as the object lives. An unsigned (``DWORD``)
field never receives a negative value: it is clamped to 0, so a malformed
mirror fails to no force rather than wrapping to a huge one.
"""

import ctypes
from ctypes import Structure

from wardogs_flight_eng.inputs.dinput_api import DiEffect, DiEnvelope
from wardogs_flight_eng.inputs.dinput_guids import (
    DIDF_ABSAXIS,
    DIEB_NOTRIGGER,
    DIEFF_CARTESIAN,
    DIEFF_OBJECTOFFSETS,
    DIEP_DIRECTION,
    DIEP_DURATION,
    DIEP_ENVELOPE,
    DIEP_GAIN,
    DIEP_NORESTART,
    DIEP_TYPESPECIFICPARAMS,
    JOYSTATE2_SIZE,
    joystate2_objects,
)
from wardogs_flight_eng.inputs.dinput_structs import (
    DICONDITION,
    DICONSTANTFORCE,
    DIDATAFORMAT,
    DIEFFECT,
    DIENVELOPE,
    DIOBJECTDATAFORMAT,
    DIPERIODIC,
    DIPROPDWORD,
    DIPROPHEADER,
    DIPROPRANGE,
    DWORD,
    LONG,
    guid_from_text,
)


class JoystickFormat:
    """``c_dfDIJoystick2``: 164 objects over the 272-byte ``DIJOYSTATE2``."""

    def __init__(self) -> None:
        rows = joystate2_objects()
        self.guids = {text: guid_from_text(text) for text, *_ in rows if text}
        self.objects = (DIOBJECTDATAFORMAT * len(rows))()
        for slot, (text, offset, kind, flags) in zip(self.objects, rows, strict=True):
            slot.pguid = ctypes.pointer(self.guids[text]) if text else None
            slot.dwOfs, slot.dwType, slot.dwFlags = offset, kind, flags
        self.format = DIDATAFORMAT(
            ctypes.sizeof(DIDATAFORMAT),
            ctypes.sizeof(DIOBJECTDATAFORMAT),
            DIDF_ABSAXIS,
            JOYSTATE2_SIZE,
            len(rows),
            self.objects,
        )


def _header(size: int, how: int, obj: int) -> DIPROPHEADER:
    return DIPROPHEADER(size, ctypes.sizeof(DIPROPHEADER), obj, how)


def property_dword(how: int, obj: int, value: int = 0) -> DIPROPDWORD:
    """A ``DIPROPDWORD`` addressed by ``how`` (``DIPH_*``) and ``obj``."""
    return DIPROPDWORD(_header(ctypes.sizeof(DIPROPDWORD), how, obj), value)


def property_range(how: int, obj: int, low: int, high: int) -> DIPROPRANGE:
    """A ``DIPROPRANGE`` addressed by ``how`` (``DIPH_*``) and ``obj``."""
    return DIPROPRANGE(_header(ctypes.sizeof(DIPROPRANGE), how, obj), low, high)


def _dword(value: int) -> int:
    return max(0, value)


def _type_specific(effect: DiEffect) -> Structure | ctypes.Array[DICONDITION]:
    """The ``DICONDITION[n]``, ``DIPERIODIC`` or ``DICONSTANTFORCE`` block."""
    if effect.periodic is not None:
        p = effect.periodic
        period = _dword(p.period_us)
        return DIPERIODIC(_dword(p.magnitude), p.offset, _dword(p.phase), period)
    if effect.constant is not None:
        return DICONSTANTFORCE(effect.constant.magnitude)
    blocks = [
        DICONDITION(
            c.offset,
            c.positive_coefficient,
            c.negative_coefficient,
            _dword(c.positive_saturation),
            _dword(c.negative_saturation),
            c.dead_band,
        )
        for c in effect.condition
    ]
    return (DICONDITION * len(blocks))(*blocks)


def _envelope(envelope: DiEnvelope | None) -> DIENVELOPE | None:
    if envelope is None:
        return None
    return DIENVELOPE(
        ctypes.sizeof(DIENVELOPE),
        _dword(envelope.attack_level),
        _dword(envelope.attack_time_us),
        _dword(envelope.fade_level),
        _dword(envelope.fade_time_us),
    )


class EffectStruct:
    """A ``DIEFFECT`` for ``effect`` (Cartesian, axes by ``DIJOFS_*`` offset)."""

    def __init__(self, effect: DiEffect) -> None:
        count = len(effect.axes)
        self.axes = (DWORD * count)(*(_dword(a) for a in effect.axes))
        self.direction = (LONG * count)(*effect.direction)
        self.params = _type_specific(effect)
        self.envelope = _envelope(effect.envelope)
        envelope = None if self.envelope is None else ctypes.pointer(self.envelope)
        self.struct = DIEFFECT(
            dwSize=ctypes.sizeof(DIEFFECT),
            dwFlags=DIEFF_CARTESIAN | DIEFF_OBJECTOFFSETS,
            dwDuration=_dword(effect.duration_us),
            dwGain=_dword(effect.gain),
            dwTriggerButton=DIEB_NOTRIGGER,
            cAxes=count,
            rgdwAxes=self.axes,
            rglDirection=self.direction,
            lpEnvelope=envelope,
            cbTypeSpecificParams=ctypes.sizeof(self.params),
            lpvTypeSpecificParams=ctypes.addressof(self.params),
        )


def parameter_flags(effect: DiEffect, norestart: bool) -> int:
    """``SetParameters`` flags for ``effect``: never ``DIEP_START``.

    ``DIEP_ENVELOPE`` is always set: an effect without an envelope sends a
    NULL ``lpEnvelope``, which removes one an earlier update left behind (a
    pooled slot reused by a transient with no fade).
    """
    flags = DIEP_DURATION | DIEP_GAIN | DIEP_DIRECTION | DIEP_TYPESPECIFICPARAMS
    flags |= DIEP_ENVELOPE
    if norestart:
        flags |= DIEP_NORESTART
    return flags
