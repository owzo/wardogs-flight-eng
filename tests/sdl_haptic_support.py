"""Helpers for the SDL haptic backend tests (built on the fake SDL)."""

from sdl_support import GUID_STICK, FakeSdl

from wardogs_flight_eng.engine.commands import Axis, Command, SineCommand, SpringCommand
from wardogs_flight_eng.inputs.sdl_api import HapticEffect
from wardogs_flight_eng.inputs.sdl_device import open_by_guid
from wardogs_flight_eng.outputs.sdl_haptic import SdlHapticBackend

PITCH_ONLY = (0, 1, 0)


def open_backend(fake: FakeSdl, length_s: float = 1.0) -> SdlHapticBackend:
    return SdlHapticBackend(
        open_by_guid(GUID_STICK, fake), persistent_length_s=length_s
    )


def effect_calls(fake: FakeSdl, name: str) -> list[tuple[int, HapticEffect]]:
    found: list[tuple[int, HapticEffect]] = []
    for effect_id, effect in fake.args(name):
        assert isinstance(effect_id, int) and isinstance(effect, HapticEffect)
        found.append((effect_id, effect))
    return found


def destroyed_ids(fake: FakeSdl) -> list[int]:
    ids = [effect_id for (effect_id,) in fake.args("SDL_HapticDestroyEffect")]
    assert all(isinstance(effect_id, int) for effect_id in ids)
    return sorted(effect_id for effect_id in ids if isinstance(effect_id, int))


def last_effect(fake: FakeSdl, kind: int) -> HapticEffect:
    return next(e for e in reversed(fake.effects.values()) if e.type == kind)


def steady_tick() -> list[Command]:
    return [
        SpringCommand(Axis.PITCH, 0.25, 0.35, 0.02),
        SpringCommand(Axis.ROLL, 0.0, 0.3, 0.02),
        SineCommand(Axis.PITCH, 5.5067, 0.4),
        SineCommand(Axis.ROLL, 5.5067, 0.4),
    ]
