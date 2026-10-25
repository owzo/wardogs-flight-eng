"""Checked DirectInput effect calls on one device, and the short-lived effect pool.

Every failing call is classified by ``checked``: a lost-device code is
``DeviceLostError``, any other failure ``DInputError``. The one exception is
``DIERR_EFFECTPLAYING`` from an in-place update (``norestart=True``), which
``update`` returns so the caller can retry it as a restart. Effects are
addressed by an ``int`` id this channel allocates; the COM effect handle stays
inside it.
"""

from collections.abc import Callable
from dataclasses import dataclass

from wardogs_flight_eng.inputs.dinput_api import (
    DIERR_EFFECTPLAYING,
    DiDeviceHandle,
    DiEffect,
    DInputError,
    DirectInputApi,
)
from wardogs_flight_eng.inputs.dinput_device import checked
from wardogs_flight_eng.inputs.protocol import DeviceLostError

POOL_SIZE = 4

ForceFailure = DeviceLostError | DInputError


def attempt(failures: list[ForceFailure], call: Callable[[], object]) -> None:
    """Run ``call``; record a force failure instead of raising it."""
    try:
        call()
    except (DeviceLostError, DInputError) as err:
        failures.append(err)


class DInputChannel:
    """The effects of one acquired DirectInput device, with status-checked calls."""

    def __init__(self, api: DirectInputApi, handle: DiDeviceHandle) -> None:
        self._api = api
        self._handle = handle
        self._effects: dict[int, object] = {}
        self._next_id = 0

    def create(self, effect: DiEffect) -> int:
        """``CreateEffect`` (downloaded, not started); the new effect's id."""
        status, effect_handle = self._api.create_effect(self._handle, effect)
        self._classify(status, "CreateEffect")
        if effect_handle is None:
            raise DInputError(f"DirectInput CreateEffect returned no {effect.kind}")
        effect_id = self._next_id
        self._next_id += 1
        self._effects[effect_id] = effect_handle
        return effect_id

    def update(self, effect_id: int, effect: DiEffect, *, norestart: bool) -> int:
        """``SetParameters``; the success status (``DI_EFFECTRESTARTED`` may be
        set), or ``DIERR_EFFECTPLAYING`` when an in-place update is refused."""
        status = self._api.set_parameters(self._effects[effect_id], effect, norestart)
        if norestart and status == DIERR_EFFECTPLAYING:
            return status
        return self._classify(status, "SetParameters")

    def start(self, effect_id: int) -> None:
        self._classify(self._api.start(self._effects[effect_id]), "Start")

    def stop(self, effect_id: int) -> None:
        self._classify(self._api.stop(self._effects[effect_id]), "Stop")

    def release(self, effect_id: int) -> None:
        """Release the effect; its id is no longer valid."""
        self._api.release_effect(self._effects.pop(effect_id))

    def stop_all(self) -> None:
        status = self._api.ff_command(self._handle, self._api.DISFFC_STOPALL)
        self._classify(status, "SendForceFeedbackCommand(DISFFC_STOPALL)")

    @staticmethod
    def _classify(status: int, call: str) -> int:
        return checked(status, call)


@dataclass(slots=True)
class _Slot:
    effect_id: int
    started: float
    ends: float


class DInputPool:
    """Up to ``POOL_SIZE`` short-lived effects of one kind on one axis.

    A new effect reuses a slot whose effect has finished, else creates a slot
    (lazily, up to the limit), else stops the oldest slot and reuses it; so a
    sustained burst never exhausts the device's effect memory and never errors.
    """

    def __init__(self, channel: DInputChannel) -> None:
        self._channel = channel
        self._slots: list[_Slot] = []

    @property
    def effect_ids(self) -> list[int]:
        return [slot.effect_id for slot in self._slots]

    def play(self, t: float, effect: DiEffect, duration_s: float) -> None:
        slot = self._claim(t)
        if slot is None:
            slot = _Slot(self._channel.create(effect), t, t + duration_s)
            self._slots.append(slot)
        else:
            # The slot is stopped or finished, so this update restarts nothing.
            self._channel.update(slot.effect_id, effect, norestart=False)
            slot.started, slot.ends = t, t + duration_s
        self._channel.start(slot.effect_id)

    def _claim(self, t: float) -> _Slot | None:
        """A finished slot, None to create one, or the stopped oldest slot."""
        finished = next((slot for slot in self._slots if slot.ends <= t), None)
        if finished is not None or len(self._slots) < POOL_SIZE:
            return finished
        oldest = min(self._slots, key=lambda slot: slot.started)
        self._channel.stop(oldest.effect_id)
        return oldest
