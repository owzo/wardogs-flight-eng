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
    DIERR_EFFECTPLAYING,
    DIERR_INPUTLOST,
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
    DiPeriodic,
    DirectInputApi,
)


def _spring() -> DiEffect:
    condition = DiCondition(0, 2500, 2500, 10000, 10000, 0)
    return DiEffect("spring", (0,), (0,), 1_000_000, 10000, condition=(condition,))


def _opened(fake: FakeDirectInput) -> object:
    handle = fake.open_device(fake.enumerate_devices()[0].instance_guid)
    assert fake.acquire(handle) == DI_OK
    return handle


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
    assert DIJOFS_BY_INDEX == (0, 4, 8, 12, 16, 20, 24, 28)


def test_enumerate_lists_the_ab9() -> None:
    (info,) = FakeDirectInput(ab9()).enumerate_devices()
    assert (info.vid, info.pid) == (PLACEHOLDER_AB9_VID, PLACEHOLDER_AB9_PID)
    assert info.product_guid == "{0010346E-0000-0000-0000-504944564944}"
    assert info.instance_name == "MOZA AB9 Base"
    assert info.force_feedback


def test_enumerate_skips_detached_devices() -> None:
    gone = dataclasses.replace(ab9(), attached=False)
    assert FakeDirectInput(gone).enumerate_devices() == []


def test_ab9_axes_and_kinds() -> None:
    fake = FakeDirectInput(ab9())
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
    handle = _opened(fake)
    assert fake.poll_state(handle)[0] == DI_OK
    device.attached = False
    assert fake.poll_state(handle)[0] == DIERR_INPUTLOST


def test_detached_device_fails_force_calls() -> None:
    device = ab9()
    fake = FakeDirectInput(device)
    handle = _opened(fake)
    _status, effect = fake.create_effect(handle, _spring())
    device.attached = False
    assert fake.start(effect) == DIERR_INPUTLOST
    assert fake.set_parameters(effect, _spring(), norestart=False) == DIERR_INPUTLOST
    assert fake.ff_command(handle, DISFFC_STOPALL) == DIERR_INPUTLOST


def test_poll_before_acquire_is_not_acquired() -> None:
    fake = FakeDirectInput(ab9())
    handle = fake.open_device(fake.enumerate_devices()[0].instance_guid)
    assert fake.poll_state(handle)[0] == DIERR_NOTACQUIRED


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
    device = dataclasses.replace(ab9(), kinds=frozenset({"spring"}))
    fake = FakeDirectInput(device)
    pulse = DiEffect("constant", (0,), (1,), 100_000, 10000, constant=DiConstant(5))
    status, effect = fake.create_effect(_opened(fake), pulse)
    assert status < 0
    assert effect is None
    assert fake.effects == {}


def test_norestart_unsupported_refuses_a_playing_update_only() -> None:
    fake = FakeDirectInput(ab9())
    fake.norestart_unsupported = True
    _status, effect = fake.create_effect(_opened(fake), _spring())
    stronger = dataclasses.replace(
        _spring(), condition=(DiCondition(0, 9000, 9000, 10000, 10000, 0),)
    )
    assert fake.set_parameters(effect, stronger, norestart=True) == DI_OK
    assert fake.start(effect) == DI_OK
    status = fake.set_parameters(effect, _spring(), norestart=True)
    assert status == DIERR_EFFECTPLAYING
    assert list(fake.effects.values()) == [stronger]
    status = fake.set_parameters(effect, _spring(), norestart=False)
    assert status == DI_EFFECTRESTARTED
    assert status >= 0
    assert list(fake.effects.values()) == [_spring()]


@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("spring", {}),
        ("sine", {"constant": DiConstant(1)}),
        ("constant", {"periodic": DiPeriodic(1, 0, 0, 1000)}),
    ],
)
def test_payload_must_match_kind(kind: str, payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="payload"):
        DiEffect(kind, (0,), (0,), 1000, 10000, **payload)  # type: ignore[arg-type]


def test_effect_direction_needs_one_entry_per_axis() -> None:
    condition = (DiCondition(0, 1, 1, 1, 1, 0),)
    with pytest.raises(ValueError, match="direction"):
        DiEffect("spring", (0, 4), (0,), 1000, 10000, condition=condition)
