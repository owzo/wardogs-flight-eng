"""The ``run`` command refuses an unboosted profile on a base without friction."""

import copy
import json
from pathlib import Path

import pytest
from cli_support import (
    BOUND_MAP,
    TickingSdl,
    bound_document,
    detach_all,
    invoke,
    joysticks_released,
    write_profile,
)
from sdl_support import FakeSdl, pedals, stick

from wardogs_flight_eng import cli
from wardogs_flight_eng.engine.profile import PROFILES_DIR


@pytest.fixture(autouse=True)
def quiet_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "setup_logging", lambda verbose: None)


@pytest.fixture
def profile(tmp_path: Path) -> Path:
    return write_profile(tmp_path / "bird.json", bound_document())


LEGACY = (
    FakeSdl.SDL_HAPTIC_CONSTANT | FakeSdl.SDL_HAPTIC_SINE | FakeSdl.SDL_HAPTIC_SPRING
)


def bound_lakota(tmp_path: Path) -> Path:
    doc = json.loads((PROFILES_DIR / "lakota.json").read_text(encoding="utf-8"))
    doc["device_map"] = copy.deepcopy(BOUND_MAP)
    return write_profile(tmp_path / "lakota.json", doc)


def test_run_refuses_unboosted_profile_without_friction(profile: Path) -> None:
    fake = TickingSdl(stick(), pedals(), after=200, then=detach_all, supported=LEGACY)
    result = invoke(["run", "--profile", str(profile)], api=fake)
    assert result.code == 1 and "unboosted" in result.output
    assert "friction" in result.output
    assert fake.count("SDL_HapticOpenFromJoystick") == 1
    assert fake.count("SDL_HapticClose") == 1 and joysticks_released(fake)
    assert fake.count("SDL_HapticNewEffect") == 0
    assert fake.count("SDL_HapticRunEffect") == 0


def test_run_refuses_unboosted_profile_when_query_is_zero(profile: Path) -> None:
    fake = TickingSdl(stick(), pedals(), after=200, then=detach_all)
    fake.query_result = 0
    result = invoke(["run", "--profile", str(profile)], api=fake)
    assert result.code == 1 and "unboosted" in result.output
    assert fake.count("SDL_HapticRunEffect") == 0


def test_run_allows_force_trim_profile_without_friction(tmp_path: Path) -> None:
    fake = TickingSdl(stick(), pedals(), after=200, then=detach_all, supported=LEGACY)
    result = invoke(["run", "--profile", str(bound_lakota(tmp_path))], api=fake)
    assert "unboosted" not in result.output and result.code == 2
