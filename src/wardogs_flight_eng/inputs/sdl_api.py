"""The SDL seam: the subset of SDL2 this package calls, plus effect mirrors.

Every SDL call goes through an ``SdlApi`` object so tests substitute a fake;
the default is the lazy real-``sdl2`` adapter in ``sdl_real``. Calls keep
SDL's names and integer status codes (negative = failure) but use Python
types: names and GUIDs come back as ``str``, handles are opaque ``object``\\ s
(``None`` where SDL returns NULL) and effects are the ``HapticEffect`` mirror
below, which the real adapter converts to a genuine ``SDL_HapticEffect``.
"""

from dataclasses import dataclass, field
from typing import Protocol

Triple = tuple[int, int, int]
_ZERO: Triple = (0, 0, 0)


class SdlError(RuntimeError):
    """An SDL call failed for a reason other than the device going away."""


@dataclass(frozen=True, slots=True)
class HapticDirection:
    """Mirror of ``SDL_HapticDirection`` (``type`` is a coordinate system)."""

    type: int = 0
    dir: Triple = _ZERO


@dataclass(frozen=True, slots=True)
class HapticCondition:
    """Mirror of ``SDL_HapticCondition``; arrays are per haptic axis (X, Y, Z)."""

    direction: HapticDirection = field(default_factory=HapticDirection)
    length: int = 0
    delay: int = 0
    right_sat: Triple = _ZERO
    left_sat: Triple = _ZERO
    right_coeff: Triple = _ZERO
    left_coeff: Triple = _ZERO
    deadband: Triple = _ZERO
    center: Triple = _ZERO


@dataclass(frozen=True, slots=True)
class HapticPeriodic:
    """Mirror of ``SDL_HapticPeriodic`` (period/lengths in ms, phase in 1/100 deg)."""

    direction: HapticDirection = field(default_factory=HapticDirection)
    length: int = 0
    delay: int = 0
    period: int = 0
    magnitude: int = 0
    offset: int = 0
    phase: int = 0
    attack_length: int = 0
    attack_level: int = 0
    fade_length: int = 0
    fade_level: int = 0


@dataclass(frozen=True, slots=True)
class HapticConstant:
    """Mirror of ``SDL_HapticConstant`` (signed ``level``)."""

    direction: HapticDirection = field(default_factory=HapticDirection)
    length: int = 0
    delay: int = 0
    level: int = 0
    attack_length: int = 0
    attack_level: int = 0
    fade_length: int = 0
    fade_level: int = 0


@dataclass(frozen=True, slots=True)
class HapticEffect:
    """Mirror of the ``SDL_HapticEffect`` union: ``type`` selects the member."""

    type: int
    condition: HapticCondition = field(default_factory=HapticCondition)
    periodic: HapticPeriodic = field(default_factory=HapticPeriodic)
    constant: HapticConstant = field(default_factory=HapticConstant)


class SdlApi(Protocol):
    """The SDL2 constants and calls the joystick and haptic layers use."""

    SDL_INIT_JOYSTICK: int
    SDL_INIT_HAPTIC: int
    SDL_HAPTIC_CONSTANT: int
    SDL_HAPTIC_SINE: int
    SDL_HAPTIC_SPRING: int
    SDL_HAPTIC_CARTESIAN: int

    def SDL_Init(self, flags: int) -> int: ...
    def SDL_GetError(self) -> str: ...
    def SDL_NumJoysticks(self) -> int: ...
    def SDL_JoystickOpen(self, index: int) -> object | None: ...
    def SDL_JoystickClose(self, joystick: object) -> None: ...
    def SDL_JoystickNameForIndex(self, index: int) -> str: ...
    def SDL_JoystickGetGUID(self, joystick: object) -> str:
        """The 32-hex GUID string ``SDL_JoystickGetGUIDString`` produces."""
        ...

    def SDL_JoystickNumAxes(self, joystick: object) -> int: ...
    def SDL_JoystickNumButtons(self, joystick: object) -> int: ...
    def SDL_JoystickGetAxis(self, joystick: object, index: int) -> int: ...
    def SDL_JoystickGetButton(self, joystick: object, index: int) -> int: ...
    def SDL_JoystickGetAttached(self, joystick: object) -> bool: ...
    def SDL_JoystickUpdate(self) -> None: ...
    def SDL_JoystickIsHaptic(self, joystick: object) -> int: ...
    def SDL_HapticOpenFromJoystick(self, joystick: object) -> object | None: ...
    def SDL_HapticQuery(self, haptic: object) -> int: ...
    def SDL_HapticNewEffect(self, haptic: object, effect: HapticEffect) -> int: ...
    def SDL_HapticUpdateEffect(
        self, haptic: object, effect_id: int, effect: HapticEffect
    ) -> int: ...
    def SDL_HapticRunEffect(
        self, haptic: object, effect_id: int, iterations: int
    ) -> int: ...
    def SDL_HapticStopEffect(self, haptic: object, effect_id: int) -> int: ...
    def SDL_HapticStopAll(self, haptic: object) -> int: ...
    def SDL_HapticDestroyEffect(self, haptic: object, effect_id: int) -> None: ...
    def SDL_HapticClose(self, haptic: object) -> None: ...
