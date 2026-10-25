"""Shared pieces of the ``--backend dinput8`` CLI tests."""

import dataclasses

import pytest
from dinput_support import FakeDiDevice, FakeDirectInput, ab9
from sdl_support import GUID_STICK

from wardogs_flight_eng import cli
from wardogs_flight_eng.inputs.dinput_api import EffectKind
from wardogs_flight_eng.outputs import backend_choice

LEGACY: frozenset[EffectKind] = frozenset({"spring", "sine", "constant"})
CHECK = ["check-device", "--guid", GUID_STICK, "--backend", "dinput8"]


def on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quiet logging; DirectInput counts as available on any test host."""
    monkeypatch.setattr(cli, "setup_logging", lambda verbose: None)
    monkeypatch.setattr(backend_choice, "_PLATFORM", "win32")


def base(kinds: frozenset[EffectKind] | None = None) -> FakeDiDevice:
    """The AB9 fake carrying ``GUID_STICK``'s vid:pid (1234:ab01)."""
    device = dataclasses.replace(ab9(), vid=0x1234, pid=0xAB01)
    if kinds is not None:
        device.kinds = kinds
    return device


def dinput8(argv: list[str]) -> list[str]:
    return [*argv, "--backend", "dinput8"]


def released(fake: FakeDirectInput) -> None:
    """The base was unacquired and released, then DirectInput itself."""
    assert fake.count("release_device") >= 1 and fake.names()[-1] == "close"
    assert not fake.devices[0].acquired
