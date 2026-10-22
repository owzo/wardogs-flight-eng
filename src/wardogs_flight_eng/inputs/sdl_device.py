"""SDL2 joysticks as ``InputDevice``\\ s: enumerate, open by GUID, read.

GUIDs are the 32-hex strings ``SDL_JoystickGetGUIDString`` produces (matched
case-insensitively). A GUID names a model, not a unit: with two identical
devices attached, ``open_by_guid`` opens the first. Every call goes through
an ``SdlApi``; ``api=None`` means the real ``sdl2`` adapter.
"""

import logging
from dataclasses import dataclass

from wardogs_flight_eng.inputs.protocol import InputConfigError, InputDevice
from wardogs_flight_eng.inputs.sdl_api import SdlApi, SdlError
from wardogs_flight_eng.inputs.sdl_real import default_api

__all__ = [
    "DeviceInfo",
    "SdlApi",
    "SdlDevice",
    "SdlError",
    "enumerate_devices",
    "open_by_guid",
]

log = logging.getLogger(__name__)

AXIS_FULL_SCALE = 32767


@dataclass(frozen=True, slots=True)
class DeviceInfo:
    """One attached joystick as SDL reports it."""

    index: int
    guid: str
    name: str
    axis_count: int
    button_count: int
    has_haptic: bool


def _started(api: SdlApi | None) -> SdlApi:
    """Resolve the api and initialise SDL's joystick and haptic subsystems."""
    resolved = default_api() if api is None else api
    if resolved.SDL_Init(resolved.SDL_INIT_JOYSTICK | resolved.SDL_INIT_HAPTIC) < 0:
        raise SdlError(f"SDL_Init failed: {resolved.SDL_GetError()}")
    return resolved


def _describe(api: SdlApi, index: int, joystick: object) -> DeviceInfo:
    return DeviceInfo(
        index=index,
        guid=api.SDL_JoystickGetGUID(joystick),
        name=api.SDL_JoystickNameForIndex(index),
        axis_count=api.SDL_JoystickNumAxes(joystick),
        button_count=api.SDL_JoystickNumButtons(joystick),
        has_haptic=api.SDL_JoystickIsHaptic(joystick) == 1,
    )


def _open(api: SdlApi, index: int) -> object | None:
    joystick = api.SDL_JoystickOpen(index)
    if joystick is None:
        log.warning("cannot open joystick %d: %s", index, api.SDL_GetError())
    return joystick


def enumerate_devices(api: SdlApi | None = None) -> list[DeviceInfo]:
    """Describe every attached joystick; each is opened and released again."""
    sdl = _started(api)
    devices: list[DeviceInfo] = []
    for index in range(sdl.SDL_NumJoysticks()):
        joystick = _open(sdl, index)
        if joystick is None:
            continue
        try:
            devices.append(_describe(sdl, index, joystick))
        finally:
            sdl.SDL_JoystickClose(joystick)
    return devices


def open_by_guid(guid: str, api: SdlApi | None = None) -> "SdlDevice":
    """Open the first joystick whose GUID is ``guid``; others are released."""
    sdl = _started(api)
    wanted = guid.lower()
    for index in range(sdl.SDL_NumJoysticks()):
        joystick = _open(sdl, index)
        if joystick is None:
            continue
        info = _describe(sdl, index, joystick)
        if info.guid.lower() == wanted:
            return SdlDevice(sdl, joystick, info)
        sdl.SDL_JoystickClose(joystick)
    raise InputConfigError(f"no joystick with GUID {guid} is attached")


class SdlDevice(InputDevice):
    """An opened SDL joystick; ``api`` and ``joystick`` serve the haptic layer.

    ``poll`` runs ``SDL_JoystickUpdate`` and refreshes ``alive`` from
    ``SDL_JoystickGetAttached``; ``axis`` scales the raw reading by 1/32767,
    clamped to -1..1.
    """

    def __init__(self, api: SdlApi, joystick: object, info: DeviceInfo) -> None:
        self.api = api
        self.joystick = joystick
        self.name = info.name
        self.guid = info.guid
        self.axis_count = info.axis_count
        self.button_count = info.button_count
        self.alive = api.SDL_JoystickGetAttached(joystick)
        self._closed = False

    def poll(self) -> None:
        if self._closed:
            return
        self.api.SDL_JoystickUpdate()
        self.alive = self.api.SDL_JoystickGetAttached(self.joystick)

    def axis(self, index: int) -> float:
        if self._closed:
            return 0.0
        raw = self.api.SDL_JoystickGetAxis(self.joystick, index)
        return max(-1.0, min(1.0, raw / AXIS_FULL_SCALE))

    def button(self, index: int) -> bool:
        if self._closed:
            return False
        return bool(self.api.SDL_JoystickGetButton(self.joystick, index))

    def close(self) -> None:
        """Release the joystick; afterwards reads return 0.0 / False, ``alive``
        is False and the SDL handle is never touched again."""
        if self._closed:
            return
        self._closed = True
        self.alive = False
        self.api.SDL_JoystickClose(self.joystick)
