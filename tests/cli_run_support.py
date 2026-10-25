"""Argument builder, bounded fake and release check for the ``run`` tests."""

from pathlib import Path

from cli_support import (
    TickingSdl,
    detach_all,
    joysticks_released,
)
from sdl_support import FakeJoystick, FakeSdl


def bounded(*joysticks: FakeJoystick) -> TickingSdl:
    """A fake that detaches everything after 200 updates: a regression that
    reaches the loop ends with exit 2 instead of hanging the suite."""
    return TickingSdl(*joysticks, after=200, then=detach_all)


def run_args(profile: Path, *extra: str) -> list[str]:
    return ["run", "--profile", str(profile), "--rate", "1000", *extra]


def released(fake: FakeSdl) -> None:
    """Haptic closed first, then both joysticks; nothing touched afterwards."""
    names = fake.names()
    assert fake.count("SDL_HapticClose") == 1
    assert joysticks_released(fake)
    assert names[-2:] == ["SDL_JoystickClose", "SDL_JoystickClose"]
    assert names.index("SDL_HapticClose") < len(names) - 2
