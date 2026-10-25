"""Fixtures for the runtime-loop tests (test_loop*.py)."""

import pytest
from backends_support import RecordingBackend
from loop_support import (
    Devices,
    TickClock,
    make_devices,
    make_engine,
    make_source,
)

from wardogs_flight_eng.engine.synth import FlightEngine
from wardogs_flight_eng.inputs.composite import CompositeInput


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
