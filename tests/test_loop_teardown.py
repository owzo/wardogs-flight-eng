"""Runtime loop: every exit path zeroes forces and releases the backend."""

import logging

import pytest
from backends_support import RecordingBackend
from loop_support import (
    FailingAllOffBackend,
    FailingApplyBackend,
    run,
)

from wardogs_flight_eng.engine.synth import FlightEngine
from wardogs_flight_eng.inputs.composite import CompositeInput


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
