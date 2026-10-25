"""Runtime loop: fixed ticks, teardown on every exit path, watchdog, profiles."""

import pytest
from backends_support import RecordingBackend
from loop_support import (
    ButtonScript,
    Devices,
    StepClock,
    TickClock,
    run,
)

from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
)
from wardogs_flight_eng.engine.profile import PROFILES_DIR, load_profile
from wardogs_flight_eng.engine.synth import FlightEngine
from wardogs_flight_eng.inputs.composite import CompositeInput
from wardogs_flight_eng.runtime.loop import run_loop


# --- the brief's tests -------------------------------------------------------
def test_loop_runs_fixed_ticks_and_tears_down(
    engine: list[FlightEngine], source: CompositeInput, fake_clock: TickClock
) -> None:
    backend = RecordingBackend()
    r = run_loop(
        engine,
        source,
        backend,
        rate_hz=100,
        watchdog_s=0.25,
        clock=fake_clock,
        sleep=lambda s: None,
        max_ticks=50,
    )
    assert r.ticks == 50 and backend.closed and backend.all_off_calls >= 1
    assert backend.events == ["apply"] * 50 + ["all_off", "close"]


def test_device_lost_ends_loop_and_zeroes_forces(
    engine: list[FlightEngine],
    source: CompositeInput,
    backend: RecordingBackend,
    devices: Devices,
    fake_clock: TickClock,
) -> None:
    devices["ped"].alive = False
    r = run_loop(
        engine,
        source,
        backend,
        rate_hz=100,
        watchdog_s=0.25,
        clock=fake_clock,
        sleep=lambda s: None,
    )
    assert r.stopped_by == "device_lost" and backend.all_off_calls >= 1
    assert backend.closed


def test_stalled_tick_applies_all_off(  # Review Focus 5
    engine: list[FlightEngine],
    source: CompositeInput,
    backend: RecordingBackend,
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = StepClock([0.0, 0.01, 0.6, 0.61])
    r = run(engine, source, backend, clock=clock, max_ticks=3)
    assert r.ticks == 3
    assert AllOffCommand() in backend.applied[1] and "watchdog" in caplog.text.lower()


def test_sleeps_until_the_next_slot_and_never_negative(
    engine: list[FlightEngine],
    source: CompositeInput,
    backend: RecordingBackend,
    devices: Devices,
) -> None:
    on_time = ButtonScript(devices, [set()])
    run(engine, source, backend, sleep=on_time, max_ticks=5)
    assert on_time.sleeps == pytest.approx([0.005] * 5)
    late = ButtonScript(devices, [set()])  # every tick overruns its 10 ms slot
    run(engine, source, backend, clock=TickClock(0.03), sleep=late, max_ticks=5)
    assert late.sleeps == [0.0] * 5


def test_run_loop_rejects_no_engines_and_still_releases(
    source: CompositeInput, backend: RecordingBackend
) -> None:
    with pytest.raises(ValueError, match="engine"):
        run_loop([], source, backend, rate_hz=100, watchdog_s=0.25)
    assert backend.all_off_calls == 1 and backend.closed


def test_loop_watchdog_overrides_a_laxer_active_engine(
    source: CompositeInput, backend: RecordingBackend
) -> None:
    lax, strict = (
        _engine_with_watchdog("littlebird-miniguns", 1.0),
        _engine_with_watchdog("lakota", 0.75),
    )
    clock = StepClock([0.0, 0.0, 0.01, 0.01, 0.91, 0.91])
    r = run_loop(
        [lax, strict],
        source,
        backend,
        rate_hz=100,
        watchdog_s=0.75,
        clock=clock,
        sleep=lambda s: None,
        max_ticks=3,
    )
    assert r.active_profile == "littlebird-miniguns"
    assert AllOffCommand() not in backend.applied[1]
    assert backend.applied[2] == [AllOffCommand()]  # 0.9 s: under 1.0, over 0.75


def _engine_with_watchdog(name: str, watchdog_s: float) -> FlightEngine:
    profile = load_profile(PROFILES_DIR / f"{name}.json")
    safety = profile.safety.model_copy(update={"watchdog_s": watchdog_s})
    return FlightEngine(profile.model_copy(update={"safety": safety}), load_constants())
