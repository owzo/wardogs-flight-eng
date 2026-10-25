"""The recording core and effect half of ``FakeDirectInput``.

``FakeEffectCalls`` records calls, applies ``fail`` injection and the
detached-device rule, and keeps created effects in memory with their owner
and playing flag. An effect handle is a ``FakeEffectHandle``; using one after
``release_effect`` or a ``DISFFC_RESET`` is a test bug (the real code never
does it), so it fails an assertion.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Protocol

from wardogs_flight_eng.inputs.dinput_api import (
    DI_EFFECTRESTARTED,
    DI_OK,
    DIERR_DEVICENOTREG,
    DIERR_EFFECTPLAYING,
    DIERR_INPUTLOST,
    DiEffect,
    EffectKind,
)


class EffectOwner(Protocol):
    attached: bool
    kinds: frozenset[EffectKind]


@dataclass(frozen=True, slots=True, eq=False)
class FakeEffectHandle:
    effect_id: int
    owner: EffectOwner


def as_effect(handle: object) -> FakeEffectHandle:
    assert isinstance(handle, FakeEffectHandle)
    return handle


class FakeEffectCalls(ABC):
    """Call log, failure injection and in-memory effects by id."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.fail: dict[str, int] = {}
        self.norestart_unsupported = False
        self.lost_code = DIERR_INPUTLOST
        self.effects: dict[int, DiEffect] = {}
        self.playing: set[int] = set()
        self._owners: dict[int, EffectOwner] = {}
        self._next_id = 0

    def names(self) -> list[str]:
        return [name for name, _ in self.calls]

    def count(self, name: str) -> int:
        return self.names().count(name)

    def args(self, name: str) -> list[tuple[object, ...]]:
        return [args for called, args in self.calls if called == name]

    def _status(
        self, name: str, args: tuple[object, ...], lost: EffectOwner | None = None
    ) -> int:
        self.calls.append((name, args))
        if name in self.fail:
            return self.fail[name]
        if lost is not None and not lost.attached:
            return self.lost_code
        return DI_OK

    def _live(self, handle: object) -> FakeEffectHandle:
        found = as_effect(handle)
        assert found.effect_id in self.effects, f"effect {found.effect_id} is gone"
        return found

    def create_effect(self, dev: object, effect: DiEffect) -> tuple[int, object]:
        owner = self._owner(dev)
        status = self._status("create_effect", (effect,), owner)
        if status < 0:
            return status, None
        if effect.kind not in owner.kinds:
            return DIERR_DEVICENOTREG, None
        effect_id = self._next_id
        self._next_id += 1
        self.effects[effect_id] = effect
        self._owners[effect_id] = owner
        self.calls[-1] = ("create_effect", (effect_id, effect))
        return status, FakeEffectHandle(effect_id, owner)

    def set_parameters(
        self, effect_handle: object, effect: DiEffect, norestart: bool
    ) -> int:
        """A driver without in-place updates (``norestart_unsupported``)
        refuses ``DIEP_NORESTART`` on a playing effect, else restarts it."""
        found = self._live(effect_handle)
        args = (found.effect_id, effect, norestart)
        status = self._status("set_parameters", args, found.owner)
        if status < 0:
            return status
        restart = found.effect_id in self.playing and self.norestart_unsupported
        if restart and norestart:
            return DIERR_EFFECTPLAYING
        self.effects[found.effect_id] = effect
        return DI_EFFECTRESTARTED if restart else DI_OK

    def start(self, effect_handle: object) -> int:
        found = self._live(effect_handle)
        status = self._status("start", (found.effect_id,), found.owner)
        if status >= 0:
            self.playing.add(found.effect_id)
        return status

    def stop(self, effect_handle: object) -> int:
        found = self._live(effect_handle)
        status = self._status("stop", (found.effect_id,), found.owner)
        if status >= 0:
            self.playing.discard(found.effect_id)
        return status

    def release_effect(self, effect_handle: object) -> None:
        effect_id = as_effect(effect_handle).effect_id
        self.calls.append(("release_effect", (effect_id,)))
        self._forget(effect_id)

    def _forget(self, effect_id: int) -> None:
        self.effects.pop(effect_id, None)
        self._owners.pop(effect_id, None)
        self.playing.discard(effect_id)

    def _owned_by(self, owner: EffectOwner) -> list[int]:
        return [i for i, found in self._owners.items() if found is owner]

    def _stop_owned(self, owner: EffectOwner) -> None:
        self.playing.difference_update(self._owned_by(owner))

    def _reset_owned(self, owner: EffectOwner) -> None:
        for effect_id in self._owned_by(owner):
            self._forget(effect_id)

    @abstractmethod
    def _owner(self, dev: object) -> EffectOwner:
        """The fake device behind a device handle."""
