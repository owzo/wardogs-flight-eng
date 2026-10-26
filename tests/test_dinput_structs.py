"""The ctypes DirectInput structs, data format and effect conversion.

Sizes are pinned for 64-bit Windows against Wine's ``include/dinput.h``
(skipped elsewhere: ``WCHAR`` and pointer sizes differ). The data format,
GUID text and ``DiEffect`` conversion are layout-independent and run
everywhere; the adapter smoke test needs Windows but no device.
"""

import ctypes
import struct
import sys

import pytest

from wardogs_flight_eng.inputs import dinput_guids as dg
from wardogs_flight_eng.inputs import dinput_real
from wardogs_flight_eng.inputs import dinput_structs as ds
from wardogs_flight_eng.inputs.dinput_api import (
    DiCondition,
    DiConstant,
    DiEffect,
    DiEnvelope,
    DiPeriodic,
)
from wardogs_flight_eng.inputs.dinput_format import (
    EffectStruct,
    JoystickFormat,
    parameter_flags,
)

WINDOWS = sys.platform == "win32"
windows64 = pytest.mark.skipif(
    not WINDOWS or struct.calcsize("P") != 8, reason="64-bit Windows layouts"
)

SIZES = {
    "DIEFFECT": 80,
    "DICONDITION": 24,
    "DIPERIODIC": 16,
    "DICONSTANTFORCE": 4,
    "DIENVELOPE": 20,
    "DIJOYSTATE2": 272,
    "DIDEVICEINSTANCEW": 1100,
    "DIDEVICEOBJECTINSTANCEW": 576,
    "DIEFFECTINFOW": 552,
    "DIDATAFORMAT": 32,
    "DIOBJECTDATAFORMAT": 24,
    "DIPROPDWORD": 20,
    "DIPROPRANGE": 24,
}


@windows64
@pytest.mark.parametrize(("name", "size"), sorted(SIZES.items()))
def test_struct_sizes_match_the_header(name: str, size: int) -> None:
    assert ctypes.sizeof(getattr(ds, name)) == size


def test_joystick2_format_has_164_objects_over_272_bytes() -> None:
    built = JoystickFormat().format
    assert (built.dwNumObjs, built.dwDataSize) == (164, 272)
    assert built.dwFlags == dg.DIDF_ABSAXIS
    rows = [built.rgodf[i] for i in range(164)]
    assert [r.dwOfs for r in rows[:8]] == [0, 4, 8, 12, 16, 20, 24, 28]
    assert ds.guid_text(rows[5].pguid.contents) == dg.GUID_RZAXIS
    assert [r.dwOfs for r in rows[12:14]] == [48, 49] and not rows[12].pguid
    assert [r.dwOfs for r in rows[140:148]] == [176, 180, 184, 188, 192, 196, 24, 28]
    assert rows[140].dwFlags == dg.DIDOI_ASPECTVELOCITY
    assert rows[-1].dwFlags == dg.DIDOI_ASPECTFORCE


@pytest.mark.parametrize(
    "text",
    [
        dg.IID_IDIRECTINPUT8W,
        *dg.EFFECT_GUIDS.values(),
        dg.GUID_XAXIS,
        dg.GUID_RXAXIS,
        "{00000000-0000-0000-0000-000000000000}",
    ],
)
def test_guid_text_round_trips(text: str) -> None:
    guid = ds.guid_from_text(text)
    assert ds.guid_text(guid) == text


def test_guid_fields_follow_the_header_layout() -> None:
    guid = ds.guid_from_text(dg.EFFECT_GUIDS["friction"])
    assert (guid.Data1, guid.Data2, guid.Data3) == (0x13541C2A, 0x8E33, 0x11D0)
    assert bytes(guid.Data4) == bytes.fromhex("9AD000A0C9A06E35")


def test_condition_effect_converts_to_a_dieffect() -> None:
    condition = DiCondition(5000, 3000, 3000, 10000, 10000, 100)
    effect = DiEffect("spring", (0, 4), (1, 0), 1_000_000, 10000, (condition,) * 2)
    built = EffectStruct(effect)
    s = built.struct
    assert s.dwSize == ctypes.sizeof(ds.DIEFFECT)
    assert s.dwFlags == dg.DIEFF_CARTESIAN | dg.DIEFF_OBJECTOFFSETS
    assert (s.dwDuration, s.dwGain, s.cAxes) == (1_000_000, 10000, 2)
    assert s.dwTriggerButton == dg.DIEB_NOTRIGGER
    assert [s.rgdwAxes[i] for i in range(2)] == [0, 4]
    assert [s.rglDirection[i] for i in range(2)] == [1, 0]
    assert s.cbTypeSpecificParams == 2 * ctypes.sizeof(ds.DICONDITION)
    blocks = ctypes.cast(s.lpvTypeSpecificParams, ctypes.POINTER(ds.DICONDITION))
    assert (blocks[1].lOffset, blocks[1].lDeadBand) == (5000, 100)
    assert not s.lpEnvelope


def test_sine_with_envelope_and_constant_convert() -> None:
    sine = DiEffect(
        "sine",
        (4,),
        (1,),
        500_000,
        10000,
        periodic=DiPeriodic(2000, 0, 9000, 200_000),
        envelope=DiEnvelope(10000, 0, 0, 100_000),
    )
    built = EffectStruct(sine)  # owns the buffers the struct points into
    s = built.struct
    periodic = ctypes.cast(s.lpvTypeSpecificParams, ctypes.POINTER(ds.DIPERIODIC))
    assert (periodic[0].dwMagnitude, periodic[0].dwPhase) == (2000, 9000)
    assert periodic[0].dwPeriod == 200_000
    assert s.lpEnvelope.contents.dwFadeTime == 100_000
    assert s.lpEnvelope.contents.dwSize == ctypes.sizeof(ds.DIENVELOPE)
    push = DiEffect("constant", (0,), (1,), 200_000, 10000, constant=DiConstant(-3000))
    pushed = EffectStruct(push)
    c = pushed.struct
    constant = ctypes.cast(c.lpvTypeSpecificParams, ctypes.POINTER(ds.DICONSTANTFORCE))
    assert constant[0].lMagnitude == -3000
    assert c.cbTypeSpecificParams == ctypes.sizeof(ds.DICONSTANTFORCE)


def test_negative_unsigned_fields_clamp_to_zero() -> None:
    sine = DiEffect("sine", (0,), (1,), -5, -1, periodic=DiPeriodic(-2000, 0, 0, 1))
    built = EffectStruct(sine)
    s = built.struct
    periodic = ctypes.cast(s.lpvTypeSpecificParams, ctypes.POINTER(ds.DIPERIODIC))
    assert (s.dwDuration, s.dwGain, periodic[0].dwMagnitude) == (0, 0, 0)


def test_parameter_flags_never_start() -> None:
    base = dg.DIEP_DURATION | dg.DIEP_GAIN | dg.DIEP_DIRECTION
    base |= dg.DIEP_TYPESPECIFICPARAMS
    plain = DiEffect("constant", (0,), (1,), 1, 1, constant=DiConstant(1))
    faded = DiEffect(
        "sine",
        (0,),
        (1,),
        1,
        1,
        periodic=DiPeriodic(1, 0, 0, 1),
        envelope=DiEnvelope(1, 0, 0, 1),
    )
    assert parameter_flags(plain, norestart=False) == base
    assert parameter_flags(plain, norestart=True) == base | dg.DIEP_NORESTART
    assert parameter_flags(faded, norestart=False) == base | dg.DIEP_ENVELOPE
    for effect in (plain, faded):
        for norestart in (False, True):
            assert not parameter_flags(effect, norestart) & dg.DIEP_START


@pytest.mark.skipif(not WINDOWS, reason="DirectInput 8 is Windows only")
def test_real_adapter_constructs_enumerates_and_closes_twice() -> None:
    api = dinput_real.RealDirectInput()
    try:
        assert isinstance(api.enumerate_devices(), list)
    finally:
        api.close()
    api.close()
    assert api.closed


@pytest.mark.skipif(not WINDOWS, reason="DirectInput 8 is Windows only")
def test_shared_rebuilds_after_close() -> None:
    first = dinput_real.shared()
    assert dinput_real.shared() is first
    first.close()
    second = dinput_real.shared()
    try:
        assert second is not first and not second.closed
    finally:
        second.close()
