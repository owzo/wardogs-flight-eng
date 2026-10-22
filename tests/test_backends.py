"""Output backends: clamp ceiling, JSONL force log and the null backend."""

import json
import logging
from pathlib import Path

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
from wardogs_flight_eng.outputs.logging_backend import LoggingBackend
from wardogs_flight_eng.outputs.null_backend import NullBackend
from wardogs_flight_eng.outputs.protocol import ForceBackend


def test_clamp_scales_magnitudes_to_ceiling() -> None:
    inner = RecordingBackend()
    b = ClampedBackend(inner, ceiling=0.6)
    b.apply(
        0.0, [SineCommand(Axis.PITCH, 5.5, 0.9), PulseCommand(Axis.ROLL, -1.0, 0.02)]
    )
    assert inner.last == [
        SineCommand(Axis.PITCH, 5.5, 0.6),
        PulseCommand(Axis.ROLL, -0.6, 0.02),
    ]


def test_logging_backend_writes_jsonl(tmp_path: Path) -> None:
    p = tmp_path / "forces.jsonl"
    b = LoggingBackend(p)
    b.apply(0.01, [SpringCommand(Axis.PITCH, 0.0, 0.35, 0.02)])
    b.all_off()
    b.close()
    lines = [json.loads(line) for line in p.read_text().splitlines()]
    assert lines[0]["kind"] == "spring" and lines[0]["coefficient"] == 0.35
    assert lines[-1]["kind"] == "all_off"


def test_clamp_limits_each_command_kind_independently() -> None:
    inner = RecordingBackend()
    b = ClampedBackend(inner, ceiling=0.5)
    b.apply(
        1.0,
        [
            SpringCommand(Axis.PITCH, 0.1, 0.8, 0.02),
            SineCommand(Axis.PITCH, 8.0, 0.7),
            PulseCommand(Axis.ROLL, 0.9, 0.05),
            TransientCommand(Axis.ROLL, 12.0, 1.0, 0.2, 0.05),
            AllOffCommand(),
        ],
    )
    assert inner.last == [
        SpringCommand(Axis.PITCH, 0.1, 0.5, 0.02),
        SineCommand(Axis.PITCH, 8.0, 0.5),
        PulseCommand(Axis.ROLL, 0.5, 0.05),
        TransientCommand(Axis.ROLL, 12.0, 0.5, 0.2, 0.05),
        AllOffCommand(),
    ]
    assert inner.times == [1.0]


def test_clamp_never_sums_same_axis_commands() -> None:
    inner = RecordingBackend()
    b = ClampedBackend(inner, ceiling=0.6)
    commands: list[Command] = [
        SineCommand(Axis.PITCH, 5.0, 0.5),
        SineCommand(Axis.PITCH, 9.0, 0.5),
    ]
    b.apply(0.0, commands)
    assert inner.last == commands


def test_clamp_passes_in_range_commands_through_unchanged() -> None:
    inner = RecordingBackend()
    b = ClampedBackend(inner, ceiling=0.6)
    commands: list[Command] = [
        SpringCommand(Axis.ROLL, 0.0, 0.6, 0.0),
        PulseCommand(Axis.PITCH, -0.6, 0.01),
    ]
    b.apply(0.0, commands)
    assert inner.last == commands
    assert all(a is c for a, c in zip(inner.last, commands, strict=True))


def test_clamp_delegates_all_off_and_close() -> None:
    inner = RecordingBackend()
    b = ClampedBackend(inner, ceiling=1.0)
    b.all_off()
    b.close()
    assert inner.all_off_calls == 1
    assert inner.closed


@pytest.mark.parametrize("ceiling", [0.0, -0.1, 1.0001, float("nan")])
def test_clamp_rejects_ceiling_outside_unit_interval(ceiling: float) -> None:
    with pytest.raises(ValueError, match="ceiling"):
        ClampedBackend(RecordingBackend(), ceiling=ceiling)


def test_logging_backend_records_every_kind(tmp_path: Path) -> None:
    p = tmp_path / "forces.jsonl"
    b = LoggingBackend(p)
    b.apply(
        0.5,
        [
            SineCommand(Axis.ROLL, 5.0, 0.25),
            PulseCommand(Axis.PITCH, -0.4, 0.02),
            TransientCommand(Axis.ROLL, 12.0, 0.3, 0.2, 0.05),
            AllOffCommand(),
        ],
    )
    b.close()
    rows = [json.loads(line) for line in p.read_text().splitlines()]
    assert rows == [
        {
            "t": 0.5,
            "kind": "sine",
            "axis": "roll",
            "frequency_hz": 5.0,
            "magnitude": 0.25,
        },
        {
            "t": 0.5,
            "kind": "pulse",
            "axis": "pitch",
            "magnitude": -0.4,
            "duration_s": 0.02,
        },
        {
            "t": 0.5,
            "kind": "transient",
            "axis": "roll",
            "frequency_hz": 12.0,
            "magnitude": 0.3,
            "duration_s": 0.2,
            "blend_out_s": 0.05,
        },
        {"t": 0.5, "kind": "all_off"},
    ]


def test_logging_backend_all_off_uses_last_time_seen(tmp_path: Path) -> None:
    p = tmp_path / "forces.jsonl"
    b = LoggingBackend(p)
    b.all_off()
    b.apply(2.5, [SineCommand(Axis.PITCH, 5.0, 0.1)])
    b.all_off()
    b.close()
    rows = [json.loads(line) for line in p.read_text().splitlines()]
    assert rows[0] == {"t": 0.0, "kind": "all_off"}
    assert rows[-1] == {"t": 2.5, "kind": "all_off"}


def test_logging_backend_close_is_idempotent_and_flushes(tmp_path: Path) -> None:
    p = tmp_path / "forces.jsonl"
    b = LoggingBackend(p)
    b.apply(0.0, [SineCommand(Axis.PITCH, 5.0, 0.1)])
    b.close()
    b.close()
    assert len(p.read_text().splitlines()) == 1
    assert p.read_text().endswith("\n")


def test_logging_backend_warns_and_ignores_calls_after_close(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    p = tmp_path / "forces.jsonl"
    b = LoggingBackend(p)
    b.close()
    with caplog.at_level(logging.WARNING):
        b.apply(0.0, [SineCommand(Axis.PITCH, 5.0, 0.1)])
        b.all_off()
    assert p.read_text() == ""
    assert [r.levelno for r in caplog.records] == [logging.WARNING, logging.WARNING]


def test_logging_backend_creates_parent_directory(tmp_path: Path) -> None:
    p = tmp_path / "nested" / "forces.jsonl"
    LoggingBackend(p).close()
    assert p.exists()


def test_null_backend_accepts_everything() -> None:
    b = NullBackend()
    b.apply(0.0, [SineCommand(Axis.PITCH, 5.0, 0.1), AllOffCommand()])
    b.all_off()
    b.close()


def test_backends_satisfy_the_protocol(tmp_path: Path) -> None:
    backends: list[ForceBackend] = [
        NullBackend(),
        RecordingBackend(),
        ClampedBackend(NullBackend(), ceiling=0.5),
        LoggingBackend(tmp_path / "f.jsonl"),
    ]
    for backend in backends:
        backend.close()
