"""Condition commands through the clamp and the JSONL force log."""

import json
from pathlib import Path

from backends_support import RecordingBackend

from wardogs_flight_eng.engine.commands import (
    Axis,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
)
from wardogs_flight_eng.outputs.clamp import ClampedBackend
from wardogs_flight_eng.outputs.logging_backend import LoggingBackend


def test_clamp_limits_condition_coefficients_to_ceiling() -> None:
    inner = RecordingBackend()
    ClampedBackend(inner, ceiling=0.3).apply(
        0.0,
        [
            FrictionCommand(Axis.PITCH, 0.9),
            DamperCommand(Axis.ROLL, 0.2),
            InertiaCommand(Axis.PITCH, float("nan")),
        ],
    )
    assert inner.last == [
        FrictionCommand(Axis.PITCH, 0.3),
        DamperCommand(Axis.ROLL, 0.2),
        InertiaCommand(Axis.PITCH, 0.0),
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
