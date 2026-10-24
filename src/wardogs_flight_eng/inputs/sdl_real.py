"""The default ``SdlApi``: a thin adapter over the real pysdl2 ``sdl2`` module.

``sdl2`` (and its DLL) is imported only when ``default_api()`` is first
called, never at module import, so tests and the pure layers stay free of it.
That first call also initialises SDL, once per process (``initialise``).
pysdl2 ships no type stubs: the module is handled as ``Any`` here and nowhere
else.
"""

import ctypes
import importlib
from dataclasses import fields
from typing import Any

from wardogs_flight_eng.inputs.sdl_api import (
    HapticDirection,
    HapticEffect,
    SdlApi,
    SdlError,
)

_GUID_BUFFER = 33  # 32 hex digits + NUL

_shared: SdlApi | None = None  # set once SDL has been initialised


def initialise(api: SdlApi) -> None:
    """Start the joystick and haptic subsystems; stop joystick events.

    Nothing pumps SDL's event queue (state is read with
    ``SDL_JoystickUpdate``), so joystick events are ignored rather than left
    to fill the queue.
    """
    if api.SDL_Init(api.SDL_INIT_JOYSTICK | api.SDL_INIT_HAPTIC) < 0:
        raise SdlError(f"SDL_Init failed: {api.SDL_GetError()}")
    api.SDL_JoystickEventState(api.SDL_IGNORE)


def default_api() -> SdlApi:
    """Import ``sdl2``, initialise SDL on the first call, return the adapter."""
    global _shared
    if _shared is None:
        sdl2: Any = importlib.import_module("sdl2")
        sdl2.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
        api = RealSdl(sdl2)
        initialise(api)
        _shared = api
    return _shared


def _member(sdl: Any, effect_type: int) -> str:
    members = {
        sdl.SDL_HAPTIC_SPRING: "condition",
        sdl.SDL_HAPTIC_DAMPER: "condition",
        sdl.SDL_HAPTIC_INERTIA: "condition",
        sdl.SDL_HAPTIC_FRICTION: "condition",
        sdl.SDL_HAPTIC_SINE: "periodic",
        sdl.SDL_HAPTIC_CONSTANT: "constant",
    }
    if effect_type not in members:
        raise ValueError(f"unsupported haptic effect type {effect_type}")
    return members[effect_type]


def _copy(target: Any, name: str, value: object) -> None:
    if isinstance(value, HapticDirection):
        direction = getattr(target, name)
        direction.type = value.type
        for index, component in enumerate(value.dir):
            direction.dir[index] = component
    elif isinstance(value, tuple):
        array = getattr(target, name)
        for index, component in enumerate(value):
            array[index] = component
    else:
        setattr(target, name, value)


def to_sdl_effect(sdl: Any, effect: HapticEffect) -> Any:
    """Build a genuine ``sdl2.SDL_HapticEffect`` from the mirror ``effect``."""
    out = sdl.SDL_HapticEffect()
    out.type = effect.type
    name = _member(sdl, effect.type)
    source, target = getattr(effect, name), getattr(out, name)
    target.type = effect.type
    for spec in fields(source):
        _copy(target, spec.name, getattr(source, spec.name))
    return out


def _text(raw: bytes | None) -> str:
    return "" if raw is None else raw.decode("utf-8", "replace")


class RealSdl:
    """``SdlApi`` over pysdl2: same calls, Python-typed arguments and results."""

    def __init__(self, sdl: Any) -> None:
        self._sdl = sdl
        self.SDL_INIT_JOYSTICK: int = sdl.SDL_INIT_JOYSTICK
        self.SDL_INIT_HAPTIC: int = sdl.SDL_INIT_HAPTIC
        self.SDL_HAPTIC_CONSTANT: int = sdl.SDL_HAPTIC_CONSTANT
        self.SDL_HAPTIC_SINE: int = sdl.SDL_HAPTIC_SINE
        self.SDL_HAPTIC_SPRING: int = sdl.SDL_HAPTIC_SPRING
        self.SDL_HAPTIC_DAMPER: int = sdl.SDL_HAPTIC_DAMPER
        self.SDL_HAPTIC_INERTIA: int = sdl.SDL_HAPTIC_INERTIA
        self.SDL_HAPTIC_FRICTION: int = sdl.SDL_HAPTIC_FRICTION
        self.SDL_HAPTIC_CARTESIAN: int = sdl.SDL_HAPTIC_CARTESIAN
        self.SDL_IGNORE: int = sdl.SDL_IGNORE

    def SDL_Init(self, flags: int) -> int:
        return int(self._sdl.SDL_Init(flags))

    def SDL_JoystickEventState(self, state: int) -> int:
        return int(self._sdl.SDL_JoystickEventState(state))

    def SDL_GetError(self) -> str:
        return _text(self._sdl.SDL_GetError())

    def SDL_NumJoysticks(self) -> int:
        return int(self._sdl.SDL_NumJoysticks())

    def SDL_JoystickOpen(self, index: int) -> object | None:
        joystick = self._sdl.SDL_JoystickOpen(index)
        return joystick if joystick else None

    def SDL_JoystickClose(self, joystick: object) -> None:
        self._sdl.SDL_JoystickClose(joystick)

    def SDL_JoystickNameForIndex(self, index: int) -> str:
        return _text(self._sdl.SDL_JoystickNameForIndex(index))

    def SDL_JoystickGetGUID(self, joystick: object) -> str:
        buffer = ctypes.create_string_buffer(_GUID_BUFFER)
        guid = self._sdl.SDL_JoystickGetGUID(joystick)
        self._sdl.SDL_JoystickGetGUIDString(guid, buffer, _GUID_BUFFER)
        return _text(buffer.value)

    def SDL_JoystickNumAxes(self, joystick: object) -> int:
        return int(self._sdl.SDL_JoystickNumAxes(joystick))

    def SDL_JoystickNumButtons(self, joystick: object) -> int:
        return int(self._sdl.SDL_JoystickNumButtons(joystick))

    def SDL_JoystickGetAxis(self, joystick: object, index: int) -> int:
        return int(self._sdl.SDL_JoystickGetAxis(joystick, index))

    def SDL_JoystickGetButton(self, joystick: object, index: int) -> int:
        return int(self._sdl.SDL_JoystickGetButton(joystick, index))

    def SDL_JoystickGetAttached(self, joystick: object) -> bool:
        return bool(self._sdl.SDL_JoystickGetAttached(joystick))

    def SDL_JoystickUpdate(self) -> None:
        self._sdl.SDL_JoystickUpdate()

    def SDL_JoystickIsHaptic(self, joystick: object) -> int:
        return int(self._sdl.SDL_JoystickIsHaptic(joystick))

    def SDL_HapticOpenFromJoystick(self, joystick: object) -> object | None:
        haptic = self._sdl.SDL_HapticOpenFromJoystick(joystick)
        return haptic if haptic else None

    def SDL_HapticQuery(self, haptic: object) -> int:
        return int(self._sdl.SDL_HapticQuery(haptic))

    def SDL_HapticNewEffect(self, haptic: object, effect: HapticEffect) -> int:
        struct = to_sdl_effect(self._sdl, effect)
        return int(self._sdl.SDL_HapticNewEffect(haptic, ctypes.byref(struct)))

    def SDL_HapticUpdateEffect(
        self, haptic: object, effect_id: int, effect: HapticEffect
    ) -> int:
        struct = to_sdl_effect(self._sdl, effect)
        status = self._sdl.SDL_HapticUpdateEffect(
            haptic, effect_id, ctypes.byref(struct)
        )
        return int(status)

    def SDL_HapticRunEffect(
        self, haptic: object, effect_id: int, iterations: int
    ) -> int:
        return int(self._sdl.SDL_HapticRunEffect(haptic, effect_id, iterations))

    def SDL_HapticStopEffect(self, haptic: object, effect_id: int) -> int:
        return int(self._sdl.SDL_HapticStopEffect(haptic, effect_id))

    def SDL_HapticStopAll(self, haptic: object) -> int:
        return int(self._sdl.SDL_HapticStopAll(haptic))

    def SDL_HapticDestroyEffect(self, haptic: object, effect_id: int) -> None:
        self._sdl.SDL_HapticDestroyEffect(haptic, effect_id)

    def SDL_HapticClose(self, haptic: object) -> None:
        self._sdl.SDL_HapticClose(haptic)
