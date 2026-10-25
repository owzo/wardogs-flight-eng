"""SDL GUID -> DirectInput instance: vid:pid parsing and instance choice."""

import dataclasses

import pytest
from dinput_support import (
    PLACEHOLDER_AB9_PID,
    PLACEHOLDER_AB9_VID,
    FakeDirectInput,
    ab9,
)

from wardogs_flight_eng.inputs.dinput_match import (
    match_sdl_guid,
    vid_pid_from_sdl_guid,
)
from wardogs_flight_eng.inputs.protocol import DeviceLostError, InputConfigError

# Windows SDL layout: bus 0003, crc, vendor 346e LE, 0, product 0010 LE, 0...
AB9_SDL_GUID = "0300ab9c6e3400001000000000000000"


def test_vid_pid_come_from_the_little_endian_words() -> None:
    expected = (PLACEHOLDER_AB9_VID, PLACEHOLDER_AB9_PID)
    assert vid_pid_from_sdl_guid(AB9_SDL_GUID) == expected
    assert vid_pid_from_sdl_guid(AB9_SDL_GUID.upper()) == expected


@pytest.mark.parametrize("bad", ["", "0300ab9c6e34", "z" * 32, "0" * 33])
def test_malformed_sdl_guid_is_a_config_error(bad: str) -> None:
    with pytest.raises(InputConfigError, match="SDL GUID"):
        vid_pid_from_sdl_guid(bad)


def test_match_prefers_the_force_feedback_instance() -> None:
    plain = dataclasses.replace(
        ab9(), instance_name="AB9 HID only", force_feedback=False
    )
    fake = FakeDirectInput(plain, ab9())
    found = match_sdl_guid(AB9_SDL_GUID, fake.enumerate_devices())
    assert found.instance_name == "MOZA AB9 Base"
    assert found.force_feedback


def test_two_force_feedback_instances_are_ambiguous_by_guid() -> None:
    fake = FakeDirectInput(ab9(), ab9())
    with pytest.raises(InputConfigError) as raised:
        match_sdl_guid(AB9_SDL_GUID, fake.enumerate_devices())
    message = str(raised.value)
    assert all(f"'MOZA AB9 Base' {d.instance_guid}" in message for d in fake.devices)


def test_no_matching_device_is_device_lost() -> None:
    detached = ab9()
    detached.attached = False
    fake = FakeDirectInput(detached)
    with pytest.raises(DeviceLostError, match="346e:0010"):
        match_sdl_guid(AB9_SDL_GUID, fake.enumerate_devices())
