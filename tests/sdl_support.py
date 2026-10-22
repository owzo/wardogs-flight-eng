"""A fake SDL for the joystick and haptic tests: records every call it gets.

It implements ``SdlApi`` with in-memory joysticks. Haptic calls fail (return
-1) while the joystick is detached, or when their name is in ``fail``, the way
SDL reports errors; ``effects`` holds each live effect's latest description.
"""

from dataclasses import dataclass, field

from wardogs_flight_eng.inputs.sdl_api import HapticEffect

GUID_STICK = "0300ab9c3412000001ab000000000000"
GUID_PEDALS = "03004e1b5a1f00000a02000000000000"


@dataclass
class FakeJoystick:
    guid: str
    name: str
    axes: list[int] = field(default_factory=lambda: [0, 0, 0])
    buttons: list[int] = field(default_factory=lambda: [0, 0])
    haptic: bool = False
    attached: bool = True


@dataclass
class FakeHaptic:
    joystick: FakeJoystick


def stick() -> FakeJoystick:
    return FakeJoystick(GUID_STICK, "MOZA AB9 Base", haptic=True)


def pedals() -> FakeJoystick:
    return FakeJoystick(GUID_PEDALS, "Rudder Pedals", axes=[0, 0, 0, 0])


def _joystick(handle: object) -> FakeJoystick:
    assert isinstance(handle, FakeJoystick)
    return handle


def _haptic(handle: object) -> FakeHaptic:
    assert isinstance(handle, FakeHaptic)
    return handle


class FakeSdl:
    """In-memory ``SdlApi``; constants carry SDL2's real values."""

    SDL_INIT_JOYSTICK = 0x200
    SDL_INIT_HAPTIC = 0x1000
    SDL_HAPTIC_CONSTANT = 1 << 0
    SDL_HAPTIC_SINE = 1 << 1
    SDL_HAPTIC_SPRING = 1 << 7
    SDL_HAPTIC_CARTESIAN = 1
    SDL_IGNORE = 0

    def __init__(self, *joysticks: FakeJoystick, supported: int | None = None) -> None:
        self.joysticks = list(joysticks)
        self.supported = (
            self.SDL_HAPTIC_CONSTANT | self.SDL_HAPTIC_SINE | self.SDL_HAPTIC_SPRING
            if supported is None
            else supported
        )
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.effects: dict[int, HapticEffect] = {}
        self.fail: set[str] = set()
        self.init_result = 0
        self._next_id = 0

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def count(self, name: str) -> int:
        return self.names().count(name)

    def args(self, name: str) -> list[tuple[object, ...]]:
        return [args for called, args in self.calls if called == name]

    def _status(self, name: str, haptic: object) -> int:
        self.calls.append((name, ()))
        if name in self.fail or not _haptic(haptic).joystick.attached:
            return -1
        return 0

    def SDL_Init(self, flags: int) -> int:
        self.calls.append(("SDL_Init", (flags,)))
        return self.init_result

    def SDL_JoystickEventState(self, state: int) -> int:
        self.calls.append(("SDL_JoystickEventState", (state,)))
        return state

    def SDL_GetError(self) -> str:
        return "fake SDL error"

    def SDL_NumJoysticks(self) -> int:
        return len(self.joysticks)

    def SDL_JoystickOpen(self, index: int) -> object | None:
        self.calls.append(("SDL_JoystickOpen", (index,)))
        return self.joysticks[index]

    def SDL_JoystickClose(self, joystick: object) -> None:
        self.calls.append(("SDL_JoystickClose", (_joystick(joystick).guid,)))

    def SDL_JoystickNameForIndex(self, index: int) -> str:
        return self.joysticks[index].name

    def SDL_JoystickGetGUID(self, joystick: object) -> str:
        return _joystick(joystick).guid

    def SDL_JoystickNumAxes(self, joystick: object) -> int:
        return len(_joystick(joystick).axes)

    def SDL_JoystickNumButtons(self, joystick: object) -> int:
        return len(_joystick(joystick).buttons)

    def SDL_JoystickGetAxis(self, joystick: object, index: int) -> int:
        return _joystick(joystick).axes[index]

    def SDL_JoystickGetButton(self, joystick: object, index: int) -> int:
        return _joystick(joystick).buttons[index]

    def SDL_JoystickGetAttached(self, joystick: object) -> bool:
        return _joystick(joystick).attached

    def SDL_JoystickUpdate(self) -> None:
        self.calls.append(("SDL_JoystickUpdate", ()))

    def SDL_JoystickIsHaptic(self, joystick: object) -> int:
        return int(_joystick(joystick).haptic)

    def SDL_HapticOpenFromJoystick(self, joystick: object) -> object | None:
        self.calls.append(("SDL_HapticOpenFromJoystick", ()))
        found = _joystick(joystick)
        return FakeHaptic(found) if found.haptic else None

    def SDL_HapticQuery(self, haptic: object) -> int:
        return self.supported

    def SDL_HapticNewEffect(self, haptic: object, effect: HapticEffect) -> int:
        if self._status("SDL_HapticNewEffect", haptic) < 0:
            return -1
        if not self.supported & effect.type:
            return -1
        effect_id = self._next_id
        self._next_id += 1
        self.effects[effect_id] = effect
        self.calls[-1] = ("SDL_HapticNewEffect", (effect_id, effect))
        return effect_id

    def SDL_HapticUpdateEffect(
        self, haptic: object, effect_id: int, effect: HapticEffect
    ) -> int:
        status = self._status("SDL_HapticUpdateEffect", haptic)
        self.calls[-1] = ("SDL_HapticUpdateEffect", (effect_id, effect))
        if status == 0:
            self.effects[effect_id] = effect
        return status

    def SDL_HapticRunEffect(
        self, haptic: object, effect_id: int, iterations: int
    ) -> int:
        status = self._status("SDL_HapticRunEffect", haptic)
        self.calls[-1] = ("SDL_HapticRunEffect", (effect_id, iterations))
        return status

    def SDL_HapticStopEffect(self, haptic: object, effect_id: int) -> int:
        status = self._status("SDL_HapticStopEffect", haptic)
        self.calls[-1] = ("SDL_HapticStopEffect", (effect_id,))
        return status

    def SDL_HapticStopAll(self, haptic: object) -> int:
        return self._status("SDL_HapticStopAll", haptic)

    def SDL_HapticDestroyEffect(self, haptic: object, effect_id: int) -> None:
        self.calls.append(("SDL_HapticDestroyEffect", (effect_id,)))
        self.effects.pop(effect_id, None)

    def SDL_HapticClose(self, haptic: object) -> None:
        self.calls.append(("SDL_HapticClose", ()))
