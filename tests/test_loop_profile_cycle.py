"""Runtime loop: profile cycling hands the rotor, latch and forces over."""

import logging

import pytest
from backends_support import RecordingBackend
from loop_support import (
    ALL_OFF_IDX,
    PROFILE_CYCLE_IDX,
    ButtonScript,
    Devices,
    TickClock,
    make_engine,
    run,
)

from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Command,
    SineCommand,
    SpringCommand,
)
from wardogs_flight_eng.engine.frame import Button, ControlFrame
from wardogs_flight_eng.engine.synth import FlightEngine
from wardogs_flight_eng.inputs.composite import CompositeInput
from wardogs_flight_eng.runtime.loop import run_loop


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
    # take_over carries the spool: one 0.01 s Littlebird tick of the 3 s spool-up,
    # then one Lakota tick, at the Lakota's 250 rpm (the Littlebird's is 330.4).
    lakota_hz = 2 * 0.01 / 3.0 * 250 / 60
    assert _sine_hz(backend.applied[1]) == pytest.approx([lakota_hz] * 2)


def test_profile_cycle_hands_over_through_take_over(
    engine_lakota: FlightEngine,
    source: CompositeInput,
    backend: RecordingBackend,
    devices: Devices,
) -> None:
    havoc = make_engine("havoc")
    for e in (engine_lakota, havoc):  # both anchors locked at (0.5, 0.5)
        e.step(0.01, ControlFrame(0.5, 0.5, 0, 0, frozenset({Button.TRIM_LOCK})))
        for _ in range(50):
            e.step(0.01, ControlFrame(0.5, 0.5, 0, 0, frozenset()))
    cycle = {PROFILE_CYCLE_IDX}
    script = ButtonScript(devices, [set(), cycle, {ALL_OFF_IDX}, cycle, set()])
    r = run([engine_lakota, havoc], source, backend, sleep=script, max_ticks=5)
    centers = [c.center for c in backend.applied[1] if isinstance(c, SpringCommand)]
    assert centers == [0.0, 0.0]  # havoc's locked anchor was dropped
    assert r.active_profile == "lakota" and engine_lakota.all_off is True
    assert backend.applied[3:] == [[AllOffCommand()], [AllOffCommand()]]


def test_profile_cycle_with_one_profile_keeps_the_trim_and_forces(
    engine_lakota: FlightEngine,
    source: CompositeInput,
    backend: RecordingBackend,
    devices: Devices,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    engine_lakota.step(
        0.01, ControlFrame(0.5, 0.5, 0, 0, frozenset({Button.TRIM_LOCK}))
    )
    for _ in range(50):  # the anchor slews fully to (0.5, 0.5)
        engine_lakota.step(0.01, ControlFrame(0.5, 0.5, 0, 0, frozenset()))
    script = ButtonScript(devices, [set(), {PROFILE_CYCLE_IDX}, set()])
    r = run([engine_lakota], source, backend, sleep=script, max_ticks=3)
    centers = [
        [c.center for c in tick if isinstance(c, SpringCommand)]
        for tick in backend.applied
    ]
    assert centers[0] and all(c != 0.0 for c in centers[0])
    assert centers == [centers[0]] * 3
    assert r.active_profile == "lakota"
    assert backend.events == ["apply", "apply", "apply", "all_off", "close"]
    assert "only one profile loaded" in caplog.text


def _sine_hz(commands: list[Command]) -> list[float]:
    return [c.frequency_hz for c in commands if isinstance(c, SineCommand)]
