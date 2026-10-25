"""Condition commands through the clamp and the JSONL force log."""

import json
from pathlib import Path

import pytest
from backends_support import RecordingBackend

from wardogs_flight_eng.engine.commands import (
    Axis,
    ConditionCommand,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
)
from wardogs_flight_eng.outputs.clamp import ClampedBackend
from wardogs_flight_eng.outputs.logging_backend import LoggingBackend


@pytest.mark.parametrize("kind", [FrictionCommand, DamperCommand, InertiaCommand])
def test_clamp_limits_and_fails_closed_per_condition_kind(
    kind: type[ConditionCommand],
) -> None:
    inner = RecordingBackend()
    ClampedBackend(inner, ceiling=0.3).apply(
        0.0,
        [
            kind(Axis.PITCH, 0.9),
            kind(Axis.ROLL, 0.2),
            kind(Axis.PITCH, float("nan")),
            kind(Axis.ROLL, float("inf")),
            kind(Axis.PITCH, -0.1),
        ],
    )
    assert inner.last == [
        kind(Axis.PITCH, 0.3),
        kind(Axis.ROLL, 0.2),
        kind(Axis.PITCH, 0.0),
        kind(Axis.ROLL, 0.0),
        kind(Axis.PITCH, 0.0),
    ]


def test_logging_backend_records_condition_kinds(tmp_path: Path) -> None:
    log = tmp_path / "f.jsonl"
    b = LoggingBackend(log)
    b.apply(
        0.5,
        [
            FrictionCommand(Axis.PITCH, 0.02),
            DamperCommand(Axis.ROLL, 0.15),
            InertiaCommand(Axis.ROLL, 0.05),
        ],
    )
    b.close()
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert [(r["kind"], r["axis"], r["coefficient"]) for r in rows] == [
        ("friction", "pitch", 0.02),
        ("damper", "roll", 0.15),
        ("inertia", "roll", 0.05),
    ]
