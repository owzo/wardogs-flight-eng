"""ClampedBackend fail-closed behaviour: non-finite values and lower bounds."""

import logging
import math
from collections.abc import Callable

import pytest
from backends_support import RecordingBackend

from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Axis,
    Command,
    PulseCommand,
    SineCommand,
    SpringCommand,
    TransientCommand,
)
from wardogs_flight_eng.outputs.clamp import ClampedBackend

NON_FINITE = [math.nan, math.inf, -math.inf]


def _spring(value: float) -> Command:
    return SpringCommand(Axis.PITCH, 0.0, value, 0.02)


def _sine(value: float) -> Command:
    return SineCommand(Axis.PITCH, 5.0, value)


def _pulse(value: float) -> Command:
    return PulseCommand(Axis.ROLL, value, 0.02)


def _transient(value: float) -> Command:
    return TransientCommand(Axis.ROLL, 12.0, value, 0.2, 0.05)


UNSIGNED = [_spring, _sine, _transient]
ALL_VALUE_COMMANDS = [*UNSIGNED, _pulse]


@pytest.mark.parametrize("make", ALL_VALUE_COMMANDS)
@pytest.mark.parametrize("bad", NON_FINITE)
def test_non_finite_value_becomes_zero_with_one_warning(
    make: Callable[[float], Command], bad: float, caplog: pytest.LogCaptureFixture
) -> None:
    inner = RecordingBackend()
    backend = ClampedBackend(inner, ceiling=0.6)
    with caplog.at_level(logging.WARNING, logger="wardogs_flight_eng.outputs.clamp"):
        backend.apply(0.0, [make(bad)])
    assert inner.last == [make(0.0)]
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "nan ->" not in warnings[0].getMessage()
    assert "non-finite" in warnings[0].getMessage()


@pytest.mark.parametrize("make", UNSIGNED)
def test_negative_value_clamps_to_zero(make: Callable[[float], Command]) -> None:
    inner = RecordingBackend()
    ClampedBackend(inner, ceiling=0.6).apply(0.0, [make(-0.3)])
    assert inner.last == [make(0.0)]


def test_pulse_keeps_negative_sign_down_to_minus_ceiling() -> None:
    inner = RecordingBackend()
    ClampedBackend(inner, ceiling=0.6).apply(
        0.0, [_pulse(-0.3), _pulse(-0.9), _pulse(0.9)]
    )
    assert inner.last == [_pulse(-0.3), _pulse(-0.6), _pulse(0.6)]


def test_all_off_command_passes_through() -> None:
    inner = RecordingBackend()
    ClampedBackend(inner, ceiling=0.6).apply(0.0, [AllOffCommand()])
    assert inner.last == [AllOffCommand()]


def test_ceiling_is_read_only() -> None:
    backend = ClampedBackend(RecordingBackend(), ceiling=0.6)
    assert backend.ceiling == 0.6
    with pytest.raises(AttributeError):
        backend.ceiling = 1.0  # type: ignore[misc]


def test_finite_clamp_warns_once_per_axis_and_kind(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = ClampedBackend(RecordingBackend(), ceiling=0.6)
    with caplog.at_level(logging.DEBUG, logger="wardogs_flight_eng.outputs.clamp"):
        for t in (0.0, 0.005, 0.01):
            backend.apply(t, [_sine(0.9)])
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "SineCommand on pitch" in warnings[0].getMessage()
        assert len([r for r in caplog.records if r.levelno == logging.DEBUG]) == 2

        backend.apply(0.015, [_spring(0.9), _spring(0.9)])
        backend.apply(0.02, [SineCommand(Axis.ROLL, 5.0, 0.9)])
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 3
    assert "SpringCommand on pitch" in warnings[1].getMessage()
    assert "SineCommand on roll" in warnings[2].getMessage()


def test_non_finite_warns_on_every_occurrence(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = ClampedBackend(RecordingBackend(), ceiling=0.6)
    with caplog.at_level(logging.WARNING, logger="wardogs_flight_eng.outputs.clamp"):
        for t in (0.0, 0.005, 0.01):
            backend.apply(t, [_sine(math.nan)])
    assert len(caplog.records) == 3
