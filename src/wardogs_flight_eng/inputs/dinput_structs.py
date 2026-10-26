"""ctypes mirrors of the dinput.h structs the adapter passes to DirectInput 8.

Layouts follow Wine's ``include/dinput.h`` field for field; on 64-bit
Windows their sizes are pinned by ``tests/test_dinput_structs.py``. Values
built from them (the data format, properties, effects) are in
``dinput_format``.
"""

import uuid
from ctypes import POINTER, Structure, c_int32, c_uint8, c_uint16, c_uint32, c_wchar
from ctypes import c_void_p as LPVOID

DWORD, LONG, WORD, BYTE = c_uint32, c_int32, c_uint16, c_uint8
MAX_PATH = 260


class GUID(Structure):
    _fields_ = [
        ("Data1", DWORD),
        ("Data2", WORD),
        ("Data3", WORD),
        ("Data4", BYTE * 8),
    ]


def guid_from_text(text: str) -> GUID:
    """``{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}`` to a ``GUID``."""
    value = uuid.UUID(text)
    data4 = (BYTE * 8)(*value.bytes[8:])
    return GUID(value.time_low, value.time_mid, value.time_hi_version, data4)


def guid_text(guid: GUID) -> str:
    """A ``GUID`` as upper-case ``{...}`` text."""
    tail = bytes(guid.Data4)
    head = f"{guid.Data1:08X}-{guid.Data2:04X}-{guid.Data3:04X}"
    return f"{{{head}-{tail[:2].hex().upper()}-{tail[2:].hex().upper()}}}"


class DIDEVICEINSTANCEW(Structure):
    _fields_ = [
        ("dwSize", DWORD),
        ("guidInstance", GUID),
        ("guidProduct", GUID),
        ("dwDevType", DWORD),
        ("tszInstanceName", c_wchar * MAX_PATH),
        ("tszProductName", c_wchar * MAX_PATH),
        ("guidFFDriver", GUID),
        ("wUsagePage", WORD),
        ("wUsage", WORD),
    ]


class DIDEVICEOBJECTINSTANCEW(Structure):
    _fields_ = [
        ("dwSize", DWORD),
        ("guidType", GUID),
        ("dwOfs", DWORD),
        ("dwType", DWORD),
        ("dwFlags", DWORD),
        ("tszName", c_wchar * MAX_PATH),
        ("dwFFMaxForce", DWORD),
        ("dwFFForceResolution", DWORD),
        ("wCollectionNumber", WORD),
        ("wDesignatorIndex", WORD),
        ("wUsagePage", WORD),
        ("wUsage", WORD),
        ("dwDimension", DWORD),
        ("wExponent", WORD),
        ("wReportId", WORD),
    ]


class DIEFFECTINFOW(Structure):
    _fields_ = [
        ("dwSize", DWORD),
        ("guid", GUID),
        ("dwEffType", DWORD),
        ("dwStaticParams", DWORD),
        ("dwDynamicParams", DWORD),
        ("tszName", c_wchar * MAX_PATH),
    ]


class DIOBJECTDATAFORMAT(Structure):
    _fields_ = [
        ("pguid", POINTER(GUID)),
        ("dwOfs", DWORD),
        ("dwType", DWORD),
        ("dwFlags", DWORD),
    ]


class DIDATAFORMAT(Structure):
    _fields_ = [
        ("dwSize", DWORD),
        ("dwObjSize", DWORD),
        ("dwFlags", DWORD),
        ("dwDataSize", DWORD),
        ("dwNumObjs", DWORD),
        ("rgodf", POINTER(DIOBJECTDATAFORMAT)),
    ]


class DIPROPHEADER(Structure):
    _fields_ = [
        ("dwSize", DWORD),
        ("dwHeaderSize", DWORD),
        ("dwObj", DWORD),
        ("dwHow", DWORD),
    ]


class DIPROPDWORD(Structure):
    _fields_ = [("diph", DIPROPHEADER), ("dwData", DWORD)]


class DIPROPRANGE(Structure):
    _fields_ = [("diph", DIPROPHEADER), ("lMin", LONG), ("lMax", LONG)]


class DICONDITION(Structure):
    _fields_ = [
        ("lOffset", LONG),
        ("lPositiveCoefficient", LONG),
        ("lNegativeCoefficient", LONG),
        ("dwPositiveSaturation", DWORD),
        ("dwNegativeSaturation", DWORD),
        ("lDeadBand", LONG),
    ]


class DIPERIODIC(Structure):
    _fields_ = [
        ("dwMagnitude", DWORD),
        ("lOffset", LONG),
        ("dwPhase", DWORD),
        ("dwPeriod", DWORD),
    ]


class DICONSTANTFORCE(Structure):
    _fields_ = [("lMagnitude", LONG)]


class DIENVELOPE(Structure):
    _fields_ = [
        ("dwSize", DWORD),
        ("dwAttackLevel", DWORD),
        ("dwAttackTime", DWORD),
        ("dwFadeLevel", DWORD),
        ("dwFadeTime", DWORD),
    ]


class DIEFFECT(Structure):
    _fields_ = [
        ("dwSize", DWORD),
        ("dwFlags", DWORD),
        ("dwDuration", DWORD),
        ("dwSamplePeriod", DWORD),
        ("dwGain", DWORD),
        ("dwTriggerButton", DWORD),
        ("dwTriggerRepeatInterval", DWORD),
        ("cAxes", DWORD),
        ("rgdwAxes", POINTER(DWORD)),
        ("rglDirection", POINTER(LONG)),
        ("lpEnvelope", POINTER(DIENVELOPE)),
        ("cbTypeSpecificParams", DWORD),
        ("lpvTypeSpecificParams", LPVOID),
        ("dwStartDelay", DWORD),
    ]


_AXES8 = ("lX", "lY", "lZ", "lRx", "lRy", "lRz")


class DIJOYSTATE2(Structure):
    _fields_ = [
        *((name, LONG) for name in _AXES8),
        ("rglSlider", LONG * 2),
        ("rgdwPOV", DWORD * 4),
        ("rgbButtons", BYTE * 128),
        ("rglVAF", LONG * 24),  # velocity, acceleration, force axis blocks
    ]

    def axis_values(self) -> tuple[int, ...]:
        """The eight position axes in ``DIJOFS_BY_INDEX`` order."""
        return (*(int(getattr(self, name)) for name in _AXES8), *self.rglSlider)
