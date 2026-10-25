"""The ``run`` command against the fake SDL: wiring, exit codes and release."""

import json
import signal
from collections.abc import Callable, Iterator
from pathlib import Path
from types import FrameType

import pytest
from cli_run_support import bounded, released, run_args
from cli_support import (
    TickingSdl,
    bound_document,
    detach_all,
    invoke,
    press_ctrl_c,
    write_profile,
)
from sdl_support import pedals, stick

from wardogs_flight_eng import cli


@pytest.fixture(autouse=True)
def quiet_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "setup_logging", lambda verbose: None)


@pytest.fixture
def profile(tmp_path: Path) -> Path:
    return write_profile(tmp_path / "bird.json", bound_document())


@pytest.fixture
def sentinel_sigint() -> Iterator[Callable[[int, FrameType | None], None]]:
    """Install a recognisable SIGINT handler for the test; restore the old one."""

    def sentinel(_signum: int, _frame: FrameType | None) -> None:
        raise AssertionError("the run's own Ctrl+C handler was not installed")

    previous = signal.signal(signal.SIGINT, sentinel)
    try:
        yield sentinel
    finally:
        signal.signal(signal.SIGINT, previous)


def test_ctrl_c_stops_cleanly_and_tees_the_force_log(
    profile: Path,
    tmp_path: Path,
    sentinel_sigint: Callable[[int, FrameType | None], None],
) -> None:
    log = tmp_path / "logs" / "forces.jsonl"
    fake = TickingSdl(stick(), pedals(), after=10, then=press_ctrl_c)
    result = invoke(run_args(profile, "--log", str(log)), api=fake)
    assert result.code == 0 and "stopped: stop after" in result.output
    assert signal.getsignal(signal.SIGINT) is sentinel_sigint
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    assert {"spring", "sine"} <= {row["kind"] for row in rows}
    assert rows[-1]["kind"] == "all_off"
    assert fake.count("SDL_HapticNewEffect") >= 2
    released(fake)


class CtrlCWhileOpeningHaptic(TickingSdl):
    """Ctrl+C arrives just after the haptic opened, inside the backend build."""

    def SDL_HapticOpenFromJoystick(self, joystick: object) -> object | None:
        haptic = super().SDL_HapticOpenFromJoystick(joystick)
        signal.raise_signal(signal.SIGINT)
        return haptic


def test_ctrl_c_while_the_backend_opens_stops_at_zero_ticks_and_releases(
    profile: Path, sentinel_sigint: Callable[[int, FrameType | None], None]
) -> None:
    fake = CtrlCWhileOpeningHaptic(stick(), pedals(), after=200, then=detach_all)
    result = invoke(run_args(profile), api=fake)
    assert result.code == 0 and "stopped: stop after 0 ticks" in result.output
    assert signal.getsignal(signal.SIGINT) is sentinel_sigint
    released(fake)


def test_force_log_records_the_clamped_commands(profile: Path, tmp_path: Path) -> None:
    document = bound_document()
    document["feel"]["spring_coefficient"] = 0.9
    document["safety"]["force_ceiling"] = 1.0
    stiff = write_profile(tmp_path / "stiff.json", document)
    log = tmp_path / "forces.jsonl"
    fake = TickingSdl(stick(), pedals(), after=10, then=press_ctrl_c)
    argv = run_args(stiff, "--profile", str(profile), "--log", str(log))
    assert invoke(argv, api=fake).code == 0  # the 0.6 ceiling of `profile` rules
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    springs = [row for row in rows if row["kind"] == "spring"]
    assert springs and max(row["coefficient"] for row in springs) <= 0.6


def test_device_lost_mid_run_exits_2_and_releases(profile: Path) -> None:
    fake = TickingSdl(stick(), pedals(), after=6, then=detach_all)
    result = invoke(run_args(profile), api=fake)
    assert result.code == 2 and "device_lost" in result.output
    released(fake)


def test_sdl_failure_mid_run_exits_2_and_releases(profile: Path) -> None:
    fake = bounded(stick(), pedals())
    fake.fail.add("SDL_HapticRunEffect")  # apply raises SdlError on tick one
    result = invoke(run_args(profile), api=fake)
    assert result.code == 2 and "stopped: error after 0 ticks" in result.output
    released(fake)


def updates_while_running(fake: TickingSdl) -> int:
    """Effect updates before the teardown's first ``SDL_HapticStopAll``."""
    names = fake.names()
    return names[: names.index("SDL_HapticStopAll")].count("SDL_HapticUpdateEffect")


def test_run_with_refresh_flag_updates_every_tick(profile: Path) -> None:
    fake = TickingSdl(stick(), pedals(), after=20, then=detach_all)
    invoke(["run", "--profile", str(profile), "--refresh-every-tick"], api=fake)
    assert updates_while_running(fake) >= 40  # >= 4 persistent effects x >= 10 ticks


def test_run_without_refresh_flag_updates_only_on_change(tmp_path: Path) -> None:
    document = bound_document()
    document["rotor"]["spool_up_s"] = 0.0  # a spooling rotor changes every tick
    steady = write_profile(tmp_path / "steady.json", document)
    fake = TickingSdl(stick(), pedals(), after=20, then=detach_all)
    invoke(["run", "--profile", str(steady)], api=fake)
    assert updates_while_running(fake) < 10
