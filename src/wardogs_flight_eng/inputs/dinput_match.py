"""Find the DirectInput instance behind an SDL joystick GUID.

On Windows ``SDL_JoystickGetGUIDString`` gives 32 hex characters holding
little-endian 16-bit words: bus, CRC, vendor, 0, product, 0, version, driver.
The vendor and product words identify the model; DirectInput reports the same
ids per attached instance, so the match is by vid:pid, preferring instances
that support force feedback.
"""

import re
from collections.abc import Sequence

from wardogs_flight_eng.inputs.dinput_api import DiDeviceInfo
from wardogs_flight_eng.inputs.protocol import DeviceLostError, InputConfigError

_SDL_GUID = re.compile(r"[0-9a-fA-F]{32}")


def _le_word(text: str) -> int:
    """A little-endian 16-bit word from its four hex characters."""
    return int(text[2:4] + text[0:2], 16)


def vid_pid_from_sdl_guid(guid: str) -> tuple[int, int]:
    """Vendor and product id from a Windows SDL joystick GUID string."""
    if _SDL_GUID.fullmatch(guid) is None:
        raise InputConfigError(f"SDL GUID {guid!r} is not 32 hexadecimal characters")
    return _le_word(guid[8:12]), _le_word(guid[16:20])


def match_sdl_guid(sdl_guid: str, infos: Sequence[DiDeviceInfo]) -> DiDeviceInfo:
    """The one attached DirectInput instance with the GUID's vid:pid.

    Force-feedback instances win over ones without; several remaining is
    ambiguous (``InputConfigError``), none is ``DeviceLostError``.
    """
    vid, pid = vid_pid_from_sdl_guid(sdl_guid)
    candidates = [info for info in infos if info.vid == vid and info.pid == pid]
    with_ff = [info for info in candidates if info.force_feedback]
    if with_ff:
        candidates = with_ff
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise DeviceLostError(
            f"no DirectInput game controller {vid:04x}:{pid:04x} "
            f"(SDL GUID {sdl_guid}) is attached"
        )
    names = ", ".join(
        f"{info.instance_name!r} {info.instance_guid}" for info in candidates
    )
    raise InputConfigError(
        f"{len(candidates)} DirectInput instances match {vid:04x}:{pid:04x} "
        f"(SDL GUID {sdl_guid}): {names}; attach only one"
    )
