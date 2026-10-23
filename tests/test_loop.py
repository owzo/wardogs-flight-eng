"""Runtime loop: fixed ticks, teardown on every exit path, watchdog, profiles."""

import logging
from typing import Any

import pytest
from backends_support import RecordingBackend
from loop_support import (
    ALL_OFF_IDX,
    PROFILE_CYCLE_IDX,
    ButtonScript,
    Devices,
    FailingAllOffBackend,
    FailingApplyBackend,
    StepClock,
    TickClock,
    make_devices,
    make_engine,
    make_source,
)

from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.commands import AllOffCommand, Command, SineCommand
from wardogs_flight_eng.engine.profile import PROFILES_DIR, load_profile
from wardogs_flight_eng.engine.synth import FlightEngine
from wardogs_flight_eng.inputs.composite import CompositeInput
from wardogs_flight_eng.runtime.loop import LoopResult, run_loop


@pytest.fixture
def fake_clock() -> TickClock:
    return TickClock(0.005)  # two reads per tick -> dt 0.01 s at 100 Hz


@pytest.fixture
def engine() -> list[FlightEngine]:
    """A single-profile engine list, the common case for ``run_loop``."""
    return [make_engine("littlebird-miniguns")]


@pytest.fixture
def engine_lb() -> FlightEngine:
    return make_engine("littlebird-miniguns")


@pytest.fixture
def engine_lakota() -> FlightEngine:
    return make_engine("lakota")


@pytest.fixture
def devices() -> Devices:
    return make_devices()


@pytest.fixture
def source(devices: Devices) -> CompositeInput:
    return make_source(devices)


@pytest.fixture
def backend() -> RecordingBackend:
    return RecordingBackend()


def run(
    engines: list[FlightEngine], source: Any, backend: RecordingBackend, **kw: Any
) -> LoopResult:
    """``run_loop`` at 100 Hz, 0.25 s watchdog, fake clock, no real sleeping."""
    options: dict[str, Any] = {"clock": TickClock(0.005), "sleep": lambda s: None}
    options.update(kw)
    return run_loop(engines, source, backend, rate_hz=100, watchdog_s=0.25, **options)


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


def test_profile_cycle_switches_engine_and_zeroes_forces(
    engine_lb: FlightEngine,
    engine_lakota: FlightEngine,
    source: CompositeInput,
    backend: RecordingBackend,
    devices: Devices,
    fake_clock: TickClock,
) -> None:
    devices["grip"].buttons[PROFILE_CYCLE_IDX] = True
    r = run_loop(
        [engine_lb, engine_lakota],
        source,
        backend,
        rate_hz=100,
        watchdog_s=0.25,
        clock=fake_clock,
        sleep=lambda s: None,
        max_ticks=2,
    )
    assert r.active_profile == "lakota" and backend.all_off_calls >= 1


# --- beyond the brief: latch carry-over across a profile switch ---------------
def test_profile_cycle_carries_the_all_off_latch(
    engine_lb: FlightEngine,
    engine_lakota: FlightEngine,
    source: CompositeInput,
    backend: RecordingBackend,
    devices: Devices,
) -> None:
    script = ButtonScript(devices, [{ALL_OFF_IDX}, set(), {PROFILE_CYCLE_IDX}, set()])
    r = run([engine_lb, engine_lakota], source, backend, sleep=script, max_ticks=4)
    assert r.active_profile == "lakota" and engine_lakota.all_off is True
    assert backend.applied[2:] == [[AllOffCommand()], [AllOffCommand()]]


def test_profile_cycle_with_all_off_still_held_keeps_forces_off(
    engine_lb: FlightEngine,
    engine_lakota: FlightEngine,
    source: CompositeInput,
    backend: RecordingBackend,
    devices: Devices,
) -> None:
    both = {ALL_OFF_IDX, PROFILE_CYCLE_IDX}
    script = ButtonScript(devices, [{ALL_OFF_IDX}, both, both, {ALL_OFF_IDX}])
    r = run([engine_lb, engine_lakota], source, backend, sleep=script, max_ticks=4)
    assert r.active_profile == "lakota" and engine_lakota.all_off is True
    assert backend.applied[1:] == [[AllOffCommand()]] * 3


def test_profile_cycle_wraps_and_logs_the_new_profile(
    engine_lb: FlightEngine,
    engine_lakota: FlightEngine,
    source: CompositeInput,
    backend: RecordingBackend,
    devices: Devices,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    cycle = {PROFILE_CYCLE_IDX}
    script = ButtonScript(devices, [cycle, set(), cycle, set()])
    r = run([engine_lb, engine_lakota], source, backend, sleep=script, max_ticks=4)
    assert r.active_profile == "littlebird-miniguns" and backend.all_off_calls == 3
    assert "lakota" in caplog.text and "littlebird-miniguns" in caplog.text


def test_profile_cycle_zeroes_forces_before_the_incoming_engine_applies(
    engine_lb: FlightEngine,
    engine_lakota: FlightEngine,
    source: CompositeInput,
    backend: RecordingBackend,
    devices: Devices,
) -> None:
    script = ButtonScript(devices, [set(), {PROFILE_CYCLE_IDX}, set()])
    r = run([engine_lb, engine_lakota], source, backend, sleep=script, max_ticks=3)
    assert r.active_profile == "lakota"
    assert backend.events == ["apply", "all_off", "apply", "apply", "all_off", "close"]
    fresh_lakota = make_engine("lakota").step(0.01, source.read())
    assert _sine_hz(backend.applied[1]) == pytest.approx(_sine_hz(fresh_lakota))


def _sine_hz(commands: list[Command]) -> list[float]:
    return [c.frequency_hz for c in commands if isinstance(c, SineCommand)]


# --- beyond the brief: every exit path zeroes forces and releases ------------
def test_apply_failure_ends_with_error_and_still_tears_down(
    engine: list[FlightEngine],
    source: CompositeInput,
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = FailingApplyBackend()
    r = run(engine, source, backend)
    assert (r.stopped_by, r.ticks) == ("error", 0)
    assert backend.all_off_calls == 1 and backend.closed
    errors = [rec for rec in caplog.records if rec.levelno == logging.ERROR]
    assert errors and errors[0].exc_info is not None


def test_all_off_failure_does_not_prevent_close(
    engine: list[FlightEngine], source: CompositeInput, caplog: pytest.LogCaptureFixture
) -> None:
    backend = FailingAllOffBackend()
    r = run(engine, source, backend, max_ticks=1)
    assert r.stopped_by == "max_ticks" and backend.closed
    assert "all_off" in caplog.text


def test_stop_callback_ends_loop_and_tears_down(
    engine: list[FlightEngine], source: CompositeInput, backend: RecordingBackend
) -> None:
    r = run(engine, source, backend, stop=lambda: len(backend.applied) >= 3)
    assert (r.stopped_by, r.ticks) == ("stop", 3)
    assert backend.all_off_calls == 1 and backend.closed


def test_interrupt_propagates_after_teardown(
    engine: list[FlightEngine], backend: RecordingBackend
) -> None:
    class InterruptedSource:
        def read(self) -> None:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run(engine, InterruptedSource(), backend)
    assert backend.all_off_calls == 1 and backend.closed


def test_interrupt_inside_teardown_all_off_still_closes(
    engine: list[FlightEngine], source: CompositeInput
) -> None:
    class InterruptingAllOff(RecordingBackend):
        def all_off(self) -> None:
            super().all_off()
            raise KeyboardInterrupt

    backend = InterruptingAllOff()
    with pytest.raises(KeyboardInterrupt):
        run(engine, source, backend, max_ticks=1)
    assert backend.all_off_calls == 1 and backend.closed


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
