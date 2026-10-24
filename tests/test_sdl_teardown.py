"""SDL haptic backend teardown against the fake SDL: all-off, loss, close, probe."""

import pytest
from sdl_haptic_support import destroyed_ids, effect_calls, open_backend, steady_tick
from sdl_support import GUID_STICK, FakeSdl, stick

from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Axis,
    PulseCommand,
    TransientCommand,
)
from wardogs_flight_eng.inputs.protocol import DeviceLostError
from wardogs_flight_eng.inputs.sdl_api import SdlError
from wardogs_flight_eng.outputs.sdl_haptic import PrimitiveReport, probe_primitives


def test_all_off_stops_everything() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake)
    backend.apply(0.0, steady_tick())
    fake.calls.clear()
    backend.all_off()
    assert fake.names()[0] == "SDL_HapticStopAll"
    zeroed = effect_calls(fake, "SDL_HapticUpdateEffect")
    assert sorted(effect_id for effect_id, _ in zeroed) == [0, 1, 2, 3]
    for _, effect in zeroed:
        assert effect.condition.right_coeff == effect.condition.left_coeff == (0, 0, 0)
        assert effect.periodic.magnitude == 0
    assert fake.count("SDL_HapticRunEffect") == 0


def test_all_off_command_stops_everything() -> None:
    fake = FakeSdl(stick())
    open_backend(fake).apply(0.0, [AllOffCommand()])
    assert fake.names()[-1] == "SDL_HapticStopAll"


def test_detached_device_raises_device_lost() -> None:
    joystick = stick()
    backend = open_backend(FakeSdl(joystick))
    backend.apply(0.0, steady_tick())
    joystick.attached = False
    with pytest.raises(DeviceLostError):
        backend.apply(0.01, steady_tick())
    with pytest.raises(DeviceLostError):
        backend.all_off()


def test_other_haptic_failure_raises_sdl_error() -> None:
    fake = FakeSdl(stick())
    fake.fail.add("SDL_HapticRunEffect")
    with pytest.raises(SdlError, match="SDL_HapticRunEffect failed: fake SDL error"):
        open_backend(fake).apply(0.0, steady_tick())


def test_close_twice_destroys_each_effect_once() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake)
    backend.apply(0.0, [*steady_tick(), PulseCommand(Axis.ROLL, 0.5, 0.02)])
    backend.apply(0.01, [TransientCommand(Axis.PITCH, 6.0, 0.3, 0.4, 0.25)])
    backend.close()
    backend.close()
    assert destroyed_ids(fake) == [0, 1, 2, 3, 4, 5]
    assert fake.count("SDL_HapticClose") == 1
    names = fake.names()
    assert names.index("SDL_HapticStopAll") < names.index("SDL_HapticDestroyEffect")


def test_close_releases_device_even_when_all_off_fails() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake)
    backend.apply(0.0, steady_tick())
    fake.fail.add("SDL_HapticStopAll")
    with pytest.raises(SdlError):
        backend.close()
    assert fake.count("SDL_HapticDestroyEffect") == 4
    assert fake.count("SDL_HapticClose") == 1
    backend.close()
    backend.all_off()
    backend.apply(0.02, steady_tick())
    assert fake.count("SDL_HapticClose") == 1
    assert fake.count("SDL_HapticRunEffect") == 4


def test_probe_reports_supported_primitives() -> None:
    fake = FakeSdl(stick())
    assert probe_primitives(GUID_STICK, fake) == PrimitiveReport(*[True] * 7)
    created = sorted(i for i, _ in effect_calls(fake, "SDL_HapticNewEffect"))
    assert len(created) == 6
    assert destroyed_ids(fake) == created
    assert fake.count("SDL_HapticClose") == 1
    assert fake.count("SDL_HapticRunEffect") == 0
    moved = effect_calls(fake, "SDL_HapticUpdateEffect")[0][1]
    assert moved.condition.center == (0, 16384, 0)


def test_probe_reports_missing_primitives() -> None:
    fake = FakeSdl(stick(), supported=FakeSdl.SDL_HAPTIC_SPRING)
    fake.fail.add("SDL_HapticUpdateEffect")
    report = probe_primitives(GUID_STICK, fake)
    assert report == PrimitiveReport(True, *[False] * 6)
