"""Checked SDL haptic calls on one device, and the short-lived effect pool.

Every failing call is classified: ``DeviceLostError`` when the joystick is no
longer attached, otherwise ``SdlError`` carrying ``SDL_GetError()``.
"""

from dataclasses import dataclass
from typing import NoReturn

from wardogs_flight_eng.inputs.protocol import DeviceLostError
from wardogs_flight_eng.inputs.sdl_api import HapticEffect, SdlApi, SdlError

POOL_SIZE = 4


class HapticChannel:
    """The haptic device opened from ``joystick``, with status-checked calls."""

    def __init__(self, api: SdlApi, joystick: object) -> None:
        self._api = api
        self._joystick = joystick
        haptic = api.SDL_HapticOpenFromJoystick(joystick)
        if haptic is None:
            self._fail("SDL_HapticOpenFromJoystick")
        self._haptic = haptic

    def require_attached(self) -> None:
        if not self._api.SDL_JoystickGetAttached(self._joystick):
            raise DeviceLostError("force-feedback device is no longer attached")

    def query(self) -> int:
        """Bit mask of supported effect types (0 if SDL cannot tell)."""
        return self._api.SDL_HapticQuery(self._haptic)

    def new(self, effect: HapticEffect) -> int:
        effect_id = self._api.SDL_HapticNewEffect(self._haptic, effect)
        self._check(effect_id, "SDL_HapticNewEffect")
        return effect_id

    def update(self, effect_id: int, effect: HapticEffect) -> None:
        status = self._api.SDL_HapticUpdateEffect(self._haptic, effect_id, effect)
        self._check(status, "SDL_HapticUpdateEffect")

    def run(self, effect_id: int) -> None:
        status = self._api.SDL_HapticRunEffect(self._haptic, effect_id, 1)
        self._check(status, "SDL_HapticRunEffect")

    def stop(self, effect_id: int) -> None:
        status = self._api.SDL_HapticStopEffect(self._haptic, effect_id)
        self._check(status, "SDL_HapticStopEffect")

    def stop_all(self) -> None:
        self._check(self._api.SDL_HapticStopAll(self._haptic), "SDL_HapticStopAll")

    def destroy(self, effect_id: int) -> None:
        self._api.SDL_HapticDestroyEffect(self._haptic, effect_id)

    def close(self) -> None:
        self._api.SDL_HapticClose(self._haptic)

    def _check(self, status: int, call: str) -> None:
        if status < 0:
            self._fail(call)

    def _fail(self, call: str) -> NoReturn:
        self.require_attached()
        raise SdlError(f"{call} failed: {self._api.SDL_GetError()}")


@dataclass(slots=True)
class _Slot:
    effect_id: int
    started: float
    ends: float


class EffectPool:
    """Up to ``POOL_SIZE`` short-lived effects of one kind on one axis.

    A new effect reuses a slot whose effect has finished, else creates a slot
    (lazily, up to the limit), else stops the oldest slot and reuses it; so a
    sustained burst never exhausts SDL's effect slots and never errors.
    """

    def __init__(self, channel: HapticChannel) -> None:
        self._channel = channel
        self._slots: list[_Slot] = []

    @property
    def effect_ids(self) -> list[int]:
        return [slot.effect_id for slot in self._slots]

    def play(self, t: float, effect: HapticEffect, duration_s: float) -> None:
        slot = self._claim(t)
        if slot is None:
            slot = _Slot(self._channel.new(effect), t, t + duration_s)
            self._slots.append(slot)
        else:
            self._channel.update(slot.effect_id, effect)
            slot.started, slot.ends = t, t + duration_s
        self._channel.run(slot.effect_id)

    def _claim(self, t: float) -> _Slot | None:
        """A finished slot, None to create one, or the stopped oldest slot."""
        finished = next((slot for slot in self._slots if slot.ends <= t), None)
        if finished is not None or len(self._slots) < POOL_SIZE:
            return finished
        oldest = min(self._slots, key=lambda slot: slot.started)
        self._channel.stop(oldest.effect_id)
        return oldest
