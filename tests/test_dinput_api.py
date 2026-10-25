"""The DirectInput seam: mirrors, HRESULT constants and the fake's contract."""

import dataclasses

import pytest
from dinput_support import (
    PLACEHOLDER_AB9_PID,
    PLACEHOLDER_AB9_VID,
    FakeDirectInput,
    ab9,
)

from wardogs_flight_eng.inputs.dinput_api import (
    DI_EFFECTRESTARTED,
    DI_OK,
    DIERR_DEVICENOTREG,
    DIERR_EFFECTPLAYING,
    DIERR_INPUTLOST,
    DIERR_INVALIDPARAM,
    DIERR_NOTACQUIRED,
    DIERR_UNPLUGGED,
    DIJOFS_BY_INDEX,
    DISFFC_RESET,
    DISFFC_SETACTUATORSON,
    DISFFC_STOPALL,
    DiCondition,
    DiConstant,
    DiEffect,
    DInputError,
    DirectInputApi,
)


def _spring() -> DiEffect:
    condition = DiCondition(0, 2500, 2500, 10000, 10000, 0)
    return DiEffect("spring", (0,), (0,), 1_000_000, 10000, condition=(condition,))


def _opened(fake: FakeDirectInput) -> object:
    handle = fake.open_device(fake.enumerate_devices()[0].instance_guid)
    assert fake.acquire(handle) == DI_OK
    return handle


def _detached() -> tuple[FakeDirectInput, object, object]:
    device = ab9()
    fake = FakeDirectInput(device)
    handle = _opened(fake)
    _status, effect = fake.create_effect(handle, _spring())
    device.attached = False
    return fake, handle, effect


def test_fake_satisfies_the_seam() -> None:
    api: DirectInputApi = FakeDirectInput(ab9())
    assert api.DISFFC_RESET == DISFFC_RESET == 1
    assert api.DISFFC_STOPALL == DISFFC_STOPALL == 2
    assert api.DISFFC_SETACTUATORSON == DISFFC_SETACTUATORSON == 0x10


def test_hresults_are_signed_header_values() -> None:
    assert DI_OK == 0
    assert DI_EFFECTRESTARTED == 4
    assert DIERR_INPUTLOST == -2147024866 == 0x8007001E - (1 << 32)
    assert DIERR_NOTACQUIRED == 0x8007000C - (1 << 32)
    assert DIERR_UNPLUGGED == 0x80040209 - (1 << 32)
    assert DIERR_EFFECTPLAYING == 0x80040208 - (1 << 32)
    assert DIERR_INVALIDPARAM == 0x80070057 - (1 << 32)
    assert DIJOFS_BY_INDEX == (0, 4, 8, 12, 16, 20, 24, 28)


def test_enumerate_lists_the_ab9_with_its_axes_and_kinds() -> None:
    fake = FakeDirectInput(ab9())
    (info,) = fake.enumerate_devices()
    assert (info.vid, info.pid) == (PLACEHOLDER_AB9_VID, PLACEHOLDER_AB9_PID)
    assert info.product_guid == "{0010346E-0000-0000-0000-504944564944}"
    assert info.instance_name == "MOZA AB9 Base"
    assert info.force_feedback
    handle = _opened(fake)
    axes = fake.axes(handle)
    assert [a.offset for a in axes] == [0, 4, 8, 20]
    assert [a.ff_actuator for a in axes] == [True, True, False, False]
    assert len(fake.enum_effect_kinds(handle)) == 6


def test_open_sequence_is_recorded_with_its_arguments() -> None:
    fake = FakeDirectInput(ab9())
    guid = fake.enumerate_devices()[0].instance_guid
    handle = fake.open_device(guid)
    fake.set_ff_gain(handle, 10000)
    fake.ff_command(handle, DISFFC_RESET)
    assert fake.names() == ["open_device", "set_ff_gain", "ff_command"]
    assert fake.args("open_device") == [(guid,)]
    assert fake.args("ff_command") == [(DISFFC_RESET,)]
    ored = DISFFC_RESET | DISFFC_SETACTUATORSON
    assert fake.ff_command(handle, ored) == DIERR_INVALIDPARAM
    assert fake.get_ff_gain(handle) == 10000
    fake.release_device(handle)
    fake.close()
    assert fake.names()[-2:] == ["release_device", "close"]
    assert fake.args("release_device") == [(guid,)]


def test_open_of_an_unknown_instance_raises() -> None:
    with pytest.raises(DInputError, match="no device"):
        FakeDirectInput(ab9()).open_device("{00000000-0000-0000-0000-000000000000}")


def test_detached_device_makes_poll_return_input_lost() -> None:
    device = ab9()
    fake = FakeDirectInput(device)
    handle = fake.open_device(device.instance_guid)
    assert fake.poll_state(handle)[0] == DIERR_NOTACQUIRED
    assert fake.acquire(handle) == DI_OK
    assert fake.poll_state(handle)[0] == DI_OK
    device.attached = False
    assert fake.poll_state(handle)[0] == DIERR_INPUTLOST
    assert fake.enumerate_devices() == []


def test_detached_device_fails_force_calls() -> None:
    fake, handle, effect = _detached()
    assert fake.start(effect) == DIERR_INPUTLOST
    assert fake.set_parameters(effect, _spring(), norestart=False) == DIERR_INPUTLOST
    assert fake.ff_command(handle, DISFFC_STOPALL) == DIERR_INPUTLOST
    assert fake.stop(effect) == DIERR_INPUTLOST
    assert fake.create_effect(handle, _spring()) == (DIERR_INPUTLOST, None)
    assert len(fake.effects) == 1
    assert fake.acquire(handle) == DIERR_INPUTLOST
    assert fake.set_ff_gain(handle, 5000) == DIERR_INPUTLOST
    assert fake.get_ff_gain(handle) == 10000


def test_teardown_calls_succeed_on_a_detached_device() -> None:
    fake, handle, effect = _detached()
    assert fake.unacquire(handle) == DI_OK
    fake.release_effect(effect)
    fake.release_device(handle)
    fake.close()
    assert fake.effects == {}
    assert fake.names()[-3:] == ["release_effect", "release_device", "close"]


def test_fail_injection_returns_the_given_code() -> None:
    fake = FakeDirectInput(ab9())
    handle = fake.open_device(fake.enumerate_devices()[0].instance_guid)
    fake.fail["acquire"] = DIERR_UNPLUGGED
    assert fake.acquire(handle) == DIERR_UNPLUGGED
    assert fake.count("acquire") == 1


def test_effects_are_held_in_memory_with_playing_flags() -> None:
    fake = FakeDirectInput(ab9())
    handle = _opened(fake)
    status, effect = fake.create_effect(handle, _spring())
    assert status == DI_OK
    (effect_id,) = fake.effects
    assert fake.effects[effect_id] == _spring()
    assert fake.start(effect) == DI_OK
    assert fake.playing == {effect_id}
    assert fake.ff_command(handle, DISFFC_STOPALL) == DI_OK
    assert fake.playing == set()
    fake.release_effect(effect)
    assert fake.effects == {}
    assert fake.args("release_effect") == [(effect_id,)]


def test_unsupported_kind_is_not_created() -> None:
    fake = FakeDirectInput(dataclasses.replace(ab9(), kinds=frozenset({"spring"})))
    pulse = DiEffect("constant", (0,), (1,), 100_000, 10000, constant=DiConstant(5))
    assert fake.create_effect(_opened(fake), pulse) == (DIERR_DEVICENOTREG, None)
    assert fake.effects == {}


def test_norestart_unsupported_refuses_a_playing_update_only() -> None:
    fake = FakeDirectInput(ab9())
    fake.norestart_unsupported = True
    _status, effect = fake.create_effect(_opened(fake), _spring())
    firm = DiCondition(0, 9000, 9000, 10000, 10000, 0)
    stronger = dataclasses.replace(_spring(), condition=(firm,))
    assert fake.set_parameters(effect, stronger, norestart=True) == DI_OK
    assert fake.start(effect) == DI_OK
    assert fake.set_parameters(effect, _spring(), norestart=True) == DIERR_EFFECTPLAYING
    assert list(fake.effects.values()) == [stronger]
    assert fake.set_parameters(effect, _spring(), norestart=False) == DI_EFFECTRESTARTED
    assert list(fake.effects.values()) == [_spring()]


def test_effect_shape_is_checked() -> None:
    condition = (DiCondition(0, 1, 1, 1, 1, 0),)
    with pytest.raises(ValueError, match="payload"):
        DiEffect("spring", (0,), (0,), 1000, 10000)
    with pytest.raises(ValueError, match="payload"):
        DiEffect("sine", (0,), (0,), 1000, 10000, constant=DiConstant(1))
    with pytest.raises(ValueError, match="payload"):
        DiEffect("sine", (0,), (0,), 1000, 10000, condition=condition)
    with pytest.raises(ValueError, match="direction"):
        DiEffect("spring", (0, 4), (0,), 1000, 10000, condition=condition)
