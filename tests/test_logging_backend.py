"""JSONL force log: record shapes, timestamps, close and directory handling."""

import json
import logging
from pathlib import Path

import pytest

from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Axis,
    PulseCommand,
    SineCommand,
    SpringCommand,
    TransientCommand,
)
from wardogs_flight_eng.outputs.logging_backend import LoggingBackend


def test_logging_backend_writes_jsonl(tmp_path: Path) -> None:
    p = tmp_path / "forces.jsonl"
    b = LoggingBackend(p)
    b.apply(0.01, [SpringCommand(Axis.PITCH, 0.0, 0.35, 0.02)])
    b.all_off()
    b.close()
    lines = [json.loads(line) for line in p.read_text().splitlines()]
    assert lines[0]["kind"] == "spring" and lines[0]["coefficient"] == 0.35
    assert lines[-1]["kind"] == "all_off"


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
