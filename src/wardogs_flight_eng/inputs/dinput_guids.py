"""The dinput.h numbers the ctypes adapter needs, as plain Python values.

GUIDs as ``{...}`` text, flags, property ids, vtable slots and the object
table of the ``DIJOYSTATE2`` data format. Every value was checked against
Wine's ``include/dinput.h`` and the ``c_dfDIJoystick2`` table in Wine's
``dlls/dinput/data_formats.c`` (which matches the Windows import library's).
No ctypes here: ``dinput_structs`` turns these into structs.
"""

from wardogs_flight_eng.inputs.dinput_api import EffectKind

DIRECTINPUT_VERSION = 0x0800
IID_IDIRECTINPUT8W = "{BF798031-483A-4DA2-AA99-5D64ED369700}"

_AXIS = "{{A36D02{:02X}-C9F3-11CF-BFC7-444553540000}}"
GUID_XAXIS, GUID_YAXIS, GUID_ZAXIS = (_AXIS.format(n) for n in (0xE0, 0xE1, 0xE2))
GUID_RXAXIS, GUID_RYAXIS = _AXIS.format(0xF4), _AXIS.format(0xF5)
GUID_RZAXIS, GUID_SLIDER = _AXIS.format(0xE3), _AXIS.format(0xE4)
GUID_POV = _AXIS.format(0xF2)

_EFFECT = "{{13541C{:02X}-8E33-11D0-9AD0-00A0C9A06E35}}"
EFFECT_GUIDS: dict[EffectKind, str] = {
    "constant": _EFFECT.format(0x20),
    "sine": _EFFECT.format(0x23),
    "spring": _EFFECT.format(0x27),
    "damper": _EFFECT.format(0x28),
    "inertia": _EFFECT.format(0x29),
    "friction": _EFFECT.format(0x2A),
}
EFFECT_KIND_BY_GUID: dict[str, EffectKind] = {g: k for k, g in EFFECT_GUIDS.items()}

# Success codes (dinput.h): DI_NOEFFECT is S_FALSE; DIERR_NOTINITIALIZED is
# HRESULT_FROM_WIN32(ERROR_NOT_READY), returned here for a released object.
DI_NOEFFECT = 1
DIERR_NOTINITIALIZED = 0x80070015 - (1 << 32)

DI8DEVCLASS_GAMECTRL = 4
DIEDFL_ATTACHEDONLY = 0x00000001
DIEDFL_FORCEFEEDBACK = 0x00000100
DIENUM_CONTINUE = 1

DIDFT_AXIS = 0x00000003
DIDFT_BUTTON = 0x0000000C
DIDFT_POV = 0x00000010
DIDFT_ANYINSTANCE = 0x00FFFF00
DIDFT_OPTIONAL = 0x80000000
DIDF_ABSAXIS = 0x00000001
DIDOI_FFACTUATOR = 0x00000001
DIDOI_ASPECTPOSITION = 0x00000100
DIDOI_ASPECTVELOCITY = 0x00000200
DIDOI_ASPECTACCEL = 0x00000300
DIDOI_ASPECTFORCE = 0x00000400

# DIPROP_* are MAKEDIPROP(n): the integer n passed where a REFGUID goes.
DIPROP_RANGE = 4
DIPROP_FFGAIN = 7
DIPROP_AUTOCENTER = 9
DIPH_DEVICE = 0
DIPH_BYOFFSET = 1
DIPROPAUTOCENTER_OFF = 0
AXIS_RANGE = (0, 65535)

DISCL_EXCLUSIVE = 0x00000001
DISCL_BACKGROUND = 0x00000008

DIEFT_ALL = 0x00000000
DIEFF_OBJECTOFFSETS = 0x00000002
DIEFF_CARTESIAN = 0x00000010
DIEB_NOTRIGGER = 0xFFFFFFFF
DIEP_DURATION = 0x00000001
DIEP_GAIN = 0x00000004
DIEP_AXES = 0x00000020
DIEP_DIRECTION = 0x00000040
DIEP_ENVELOPE = 0x00000080
DIEP_TYPESPECIFICPARAMS = 0x00000100
DIEP_START = 0x20000000
DIEP_NORESTART = 0x40000000

# Vtable slots (IUnknown takes 0..2: QueryInterface, AddRef, Release).
RELEASE_SLOT = 2
DIRECTINPUT8_SLOTS = {"CreateDevice": 3, "EnumDevices": 4}
DEVICE8_SLOTS = {
    "GetCapabilities": 3,
    "EnumObjects": 4,
    "GetProperty": 5,
    "SetProperty": 6,
    "Acquire": 7,
    "Unacquire": 8,
    "GetDeviceState": 9,
    "SetDataFormat": 11,
    "SetCooperativeLevel": 13,
    "CreateEffect": 18,
    "EnumEffects": 19,
    "SendForceFeedbackCommand": 22,
    "Poll": 25,
}
EFFECT_SLOTS = {"SetParameters": 6, "Start": 7, "Stop": 8}

# DIJOYSTATE2 layout: 8 position axes from 0, 4 POVs from 32, 128 buttons
# from 48, then velocity / acceleration / force axis blocks of 8 LONGs each.
JOYSTATE2_SIZE = 272
_POV_BASE, _BUTTON_BASE = 32, 48
_ASPECT_BASES = (
    (DIDOI_ASPECTVELOCITY, 176),
    (DIDOI_ASPECTACCEL, 208),
    (DIDOI_ASPECTFORCE, 240),
)
_AXIS_GUIDS = (
    GUID_XAXIS,
    GUID_YAXIS,
    GUID_ZAXIS,
    GUID_RXAXIS,
    GUID_RYAXIS,
    GUID_RZAXIS,
)
_SLIDER_OFFSETS = (24, 28)
_AXIS_TYPE = DIDFT_OPTIONAL | DIDFT_AXIS | DIDFT_ANYINSTANCE

ObjectFormat = tuple[str | None, int, int, int]  # (pguid, dwOfs, dwType, dwFlags)


def _axis_block(base: int, aspect: int) -> list[ObjectFormat]:
    """Six axes from ``base`` and the two sliders of one aspect.

    As in Windows' own ``c_dfDIJoystick2``, the velocity, acceleration and
    force sliders carry the position sliders' offsets (24 and 28).
    """
    rows: list[ObjectFormat] = [
        (guid, base + 4 * index, _AXIS_TYPE, aspect)
        for index, guid in enumerate(_AXIS_GUIDS)
    ]
    rows += [(GUID_SLIDER, ofs, _AXIS_TYPE, aspect) for ofs in _SLIDER_OFFSETS]
    return rows


def joystate2_objects() -> list[ObjectFormat]:
    """The 164 ``DIOBJECTDATAFORMAT`` rows of ``c_dfDIJoystick2``, in order."""
    rows = _axis_block(0, DIDOI_ASPECTPOSITION)
    pov_type = DIDFT_OPTIONAL | DIDFT_POV | DIDFT_ANYINSTANCE
    rows += [(GUID_POV, _POV_BASE + 4 * n, pov_type, 0) for n in range(4)]
    button_type = DIDFT_OPTIONAL | DIDFT_BUTTON | DIDFT_ANYINSTANCE
    rows += [(None, _BUTTON_BASE + n, button_type, 0) for n in range(128)]
    for aspect, base in _ASPECT_BASES:
        rows += _axis_block(base, aspect)
    return rows
