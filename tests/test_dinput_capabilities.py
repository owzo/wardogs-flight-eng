"""Which DirectInput condition kinds the base reports, warned once at open."""

import logging

import pytest
from dinput_support import FakeDirectInput, ab9

from wardogs_flight_eng.engine.commands import (
    Axis,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
)
from wardogs_flight_eng.outputs.dinput_capabilities import DInputConditionSupport

ALL_MISSING = frozenset({"friction", "damper", "inertia"})


def test_missing_kinds_warn_once_each_at_construction(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        support = DInputConditionSupport(frozenset({"spring", "sine", "constant"}))
    assert support.missing == ALL_MISSING
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert sorted(r.getMessage() for r in warnings) == [
        f"the base reports no {kind} primitive; the feel runs without it"
        for kind in ("damper", "friction", "inertia")
    ]
    caplog.clear()
    with caplog.at_level(logging.DEBUG):
        assert not support.allows(FrictionCommand(Axis.PITCH, 0.2))
        assert not support.allows(DamperCommand(Axis.ROLL, 0.2))
        assert not support.allows(InertiaCommand(Axis.ROLL, 0.2))
    assert caplog.records == []


def test_reported_kinds_are_allowed_silently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        support = DInputConditionSupport(frozenset({"spring", "damper", "inertia"}))
        assert support.allows(DamperCommand(Axis.PITCH, 0.3))
        assert support.allows(InertiaCommand(Axis.PITCH, 0.3))
        assert not support.allows(FrictionCommand(Axis.PITCH, 0.3))
    assert support.missing == frozenset({"friction"})
    assert [r.getMessage() for r in caplog.records] == [
        "the base reports no friction primitive; the feel runs without it"
    ]


def test_no_reported_kinds_disables_all_three_under_one_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        support = DInputConditionSupport(frozenset())
    assert support.missing == ALL_MISSING
    assert [r.getMessage() for r in caplog.records] == [
        "the base did not report its capabilities; "
        "friction, damper and inertia are disabled"
    ]


def test_from_device_reads_the_enumerated_kinds() -> None:
    device = ab9()
    device.kinds = frozenset({"spring", "friction", "sine"})
    support = DInputConditionSupport.from_device(FakeDirectInput(device), device)
    assert support.missing == frozenset({"damper", "inertia"})
    full = ab9()
    assert (
        DInputConditionSupport.from_device(FakeDirectInput(full), full).missing
        == frozenset()
    )
