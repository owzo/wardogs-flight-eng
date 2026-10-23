"""``run`` safety: Ctrl+C during teardown, honest release reports, and the
ratified multi-profile parameters (lowest ceiling, shortest watchdog)."""

import json
import logging
import signal
from pathlib import Path
from typing import Any

import pytest
from cli_support import (
    TeardownSdl,
    TickingSdl,
    bound_document,
    interrupt,
    invoke,
    joysticks_released,
    press_ctrl_c,
    spring_lengths,
    write_profile,
)
from sdl_support import pedals, stick

from wardogs_flight_eng import cli
from wardogs_flight_eng.cli_interrupt import CTRL_C_GRACE_S, ctrl_c_requests_stop


@pytest.fixture(autouse=True)
def quiet_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "setup_logging", lambda verbose: None)


def _profile(tmp_path: Path, name: str, spring: float = 0.9, **safety: float) -> Path:
    """A stiff profile; its own ceiling (default 1.0) admits ``spring``."""
    document: dict[str, Any] = bound_document()
    document["name"] = name
    document["feel"]["spring_coefficient"] = spring
    document["safety"].update({"force_ceiling": 1.0, **safety})
    return write_profile(tmp_path / f"{name}.json", document)


def _run(*profiles: Path, log: Path | None = None) -> list[str]:
    argv = ["run", "--rate", "1000"]
    for path in profiles:
        argv += ["--profile", str(path)]
    return argv + ([] if log is None else ["--log", str(log)])


def _stopping(**hooks: Any) -> TeardownSdl:
    """First Ctrl+C after five ticks; ``hooks`` fire during the teardown."""
    return TeardownSdl(stick(), pedals(), after=10, then=press_ctrl_c, **hooks)


def test_second_ctrl_c_during_teardown_is_ignored(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    fake = _stopping(on_stop_all=lambda: signal.raise_signal(signal.SIGINT))
    with caplog.at_level(logging.WARNING):
        result = invoke(_run(_profile(tmp_path, "bird")), api=fake)
    assert result.code == 0 and "stopped: stop after" in result.output
    assert "already stopping" in caplog.text
    assert fake.count("SDL_HapticClose") == 1 and joysticks_released(fake)


def test_interrupt_in_teardown_all_off_still_releases(tmp_path: Path) -> None:
    fake = _stopping(on_stop_all=interrupt)
    result = invoke(_run(_profile(tmp_path, "bird")), api=fake)
    assert result.code == 0
    assert "interrupted" in result.output and "base released" in result.output
    assert fake.count("SDL_HapticClose") == 1 and joysticks_released(fake)


def test_unconfirmed_release_is_never_claimed(tmp_path: Path) -> None:
    fake = _stopping(on_close=interrupt)
    result = invoke(_run(_profile(tmp_path, "bird")), api=fake)
    assert result.code == 2
    assert "released" not in result.output and "power-cycle" in result.output
    assert fake.count("SDL_HapticClose") == 0 and joysticks_released(fake)


def test_a_ctrl_c_after_the_grace_deadline_interrupts() -> None:
    now = [100.0]
    with ctrl_c_requests_stop(clock=lambda: now[0]) as stop:
        signal.raise_signal(signal.SIGINT)
        assert stop.is_set()
        now[0] += CTRL_C_GRACE_S - 0.1
        signal.raise_signal(signal.SIGINT)  # still inside the grace: ignored
        now[0] += 0.1
        with pytest.raises(KeyboardInterrupt):
            signal.raise_signal(signal.SIGINT)


def test_lowest_force_ceiling_of_all_profiles_clamps(tmp_path: Path) -> None:
    first = _profile(tmp_path, "first", force_ceiling=1.0)
    soft = bound_document()  # every gain within its own 0.3 ceiling
    soft["name"] = "second"
    soft["feel"]["spring_coefficient"] = soft["recoil"]["amplitude"] = 0.3
    soft["safety"]["force_ceiling"] = 0.3
    second = write_profile(tmp_path / "second.json", soft)
    log = tmp_path / "forces.jsonl"
    fake = TickingSdl(stick(), pedals(), after=10, then=press_ctrl_c)
    assert invoke(_run(first, second, log=log), api=fake).code == 0
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    springs = [row["coefficient"] for row in rows if row["kind"] == "spring"]
    assert springs and max(springs) == pytest.approx(0.3)


@pytest.mark.parametrize(("watchdog_s", "length_ms"), [(0.25, 1000), (1.0, 2000)])
def test_persistent_length_is_twice_the_watchdog_at_least_a_second(
    tmp_path: Path, watchdog_s: float, length_ms: int
) -> None:
    profile = _profile(tmp_path, "bird", watchdog_s=watchdog_s)
    fake = TickingSdl(stick(), pedals(), after=10, then=press_ctrl_c)
    assert invoke(_run(profile), api=fake).code == 0
    assert spring_lengths(fake) == {length_ms}


def test_shortest_watchdog_of_all_profiles_sets_the_length(tmp_path: Path) -> None:
    first = _profile(tmp_path, "first", watchdog_s=1.0)
    second = _profile(tmp_path, "second", watchdog_s=0.75)
    fake = TickingSdl(stick(), pedals(), after=10, then=press_ctrl_c)
    assert invoke(_run(first, second), api=fake).code == 0
    assert spring_lengths(fake) == {1500}
