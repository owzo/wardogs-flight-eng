"""``run --backend dinput8``: the base through DirectInput, the rest through SDL."""

from pathlib import Path

import pytest
from cli_dinput_support import CHECK, LEGACY, base, dinput8, on_windows, released
from cli_run_support import run_args
from cli_support import (
    TickingSdl,
    bound_document,
    detach_all,
    invoke,
    write_profile,
)
from dinput_support import FakeDiDevice, FakeDirectInput
from sdl_support import GUID_PEDALS, GUID_STICK, pedals, stick

from wardogs_flight_eng.outputs import backend_choice


@pytest.fixture(autouse=True)
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    on_windows(monkeypatch)


@pytest.fixture
def profile(tmp_path: Path) -> Path:
    return write_profile(tmp_path / "bird.json", bound_document())


def sdl_fake() -> TickingSdl:
    return TickingSdl(stick(), pedals(), after=20, then=detach_all)


def test_run_dinput8_opens_the_base_through_directinput_only(profile: Path) -> None:
    sdl, di = sdl_fake(), FakeDirectInput(base())
    result = invoke(dinput8(run_args(profile)), api=sdl, dinput_api=di)
    assert result.code == 2 and "device_lost" in result.output
    assert sdl.count("SDL_HapticOpenFromJoystick") == 0
    # The pedals' GUID scan opens and closes the stick; only the pedals stay.
    assert sdl.args("SDL_JoystickOpen") == [(0,), (1,)]
    assert sdl.args("SDL_JoystickClose") == [(GUID_STICK,), (GUID_PEDALS,)]
    assert di.count("acquire") == 1 and di.count("create_effect") > 0
    released(di)


class WatchingDirectInput(FakeDirectInput):
    """Records the SDL calls made before the base is opened."""

    def __init__(self, sdl: TickingSdl, *devices: FakeDiDevice) -> None:
        super().__init__(*devices)
        self.sdl, self.sdl_before_open = sdl, list[str]()

    def open_device(self, instance_guid: str) -> object:
        self.sdl_before_open = self.sdl.names()
        return super().open_device(instance_guid)


def test_sdl_devices_open_before_the_directinput_base(profile: Path) -> None:
    sdl = sdl_fake()
    di = WatchingDirectInput(sdl, base())
    invoke(dinput8(run_args(profile)), api=sdl, dinput_api=di)
    before = di.sdl_before_open
    assert before.count("SDL_JoystickOpen") == 2
    assert before.count("SDL_JoystickClose") == 1  # the stick, scanned and closed


def test_refresh_every_tick_is_sdl_only(profile: Path) -> None:
    sdl, di = sdl_fake(), FakeDirectInput(base())
    argv = dinput8(run_args(profile, "--refresh-every-tick"))
    result = invoke(argv, api=sdl, dinput_api=di)
    assert result.code == 1 and "refresh-every-tick" in result.output
    assert sdl.count("SDL_JoystickOpen") == 0 and di.calls == []


@pytest.mark.parametrize(
    "argv",
    [
        ["run", "--profile", "{profile}"],
        ["check-device", "--guid", GUID_STICK],
        ["list-devices"],
    ],
)
def test_dinput8_is_refused_off_windows(
    argv: list[str], profile: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backend_choice, "_PLATFORM", "linux")
    sdl, di = sdl_fake(), FakeDirectInput(base())
    args = [arg.format(profile=profile) for arg in argv]
    result = invoke(dinput8(args), api=sdl, dinput_api=di)
    assert result.code == 1 and "dinput8 is not available on linux" in result.output
    assert sdl.count("SDL_JoystickOpen") == 0 and di.calls == []


def test_ambiguous_base_exits_1_naming_both_instances(profile: Path) -> None:
    sdl, di = sdl_fake(), FakeDirectInput(base(), base())
    for argv in (dinput8(run_args(profile)), CHECK):
        result = invoke(argv, api=sdl, dinput_api=di)
        assert result.code == 1
        assert all(d.instance_guid in result.output for d in di.devices)
    # The pedals opened first and were closed again: all or none stay open.
    assert sdl.count("SDL_JoystickOpen") == sdl.count("SDL_JoystickClose")
    assert di.count("open_device") == 0 and di.names() == ["close", "close"]


def test_unboosted_profile_without_friction_is_refused(profile: Path) -> None:
    sdl = sdl_fake()
    di = FakeDirectInput(base(LEGACY))
    result = invoke(dinput8(run_args(profile)), api=sdl, dinput_api=di)
    assert result.code == 1 and "unboosted" in result.output
    assert "reports no friction primitive" in result.output
    assert di.count("create_effect") == 0 and di.count("start") == 0
    assert sdl.args("SDL_JoystickClose") == [(GUID_STICK,), (GUID_PEDALS,)]
    released(di)


def test_pitch_on_an_axis_without_an_actuator_exits_1(tmp_path: Path) -> None:
    document = bound_document()
    document["device_map"]["axes"]["pitch"]["axis"] = 2
    document["device_map"]["axes"]["collective"]["axis"] = 1
    profile = write_profile(tmp_path / "z.json", document)
    di = FakeDirectInput(base())
    result = invoke(dinput8(run_args(profile)), api=sdl_fake(), dinput_api=di)
    assert result.code == 1 and "Z Axis" in result.output
    assert "not a force-feedback actuator" in result.output
    released(di)


def test_a_base_without_a_guid_cannot_use_dinput8(tmp_path: Path) -> None:
    document = bound_document()
    document["device_map"]["devices"]["base"] = {"guid": None, "product": "AB9"}
    profile = write_profile(tmp_path / "noguid.json", document)
    sdl, di = sdl_fake(), FakeDirectInput(base())
    result = invoke(dinput8(run_args(profile)), api=sdl, dinput_api=di)
    assert result.code == 1 and "device_map.devices.base" in result.output
    assert "guid" in result.output and di.count("open_device") == 0
