"""AB9 conformance check on real hardware; skipped unless ``WFE_HARDWARE=1``.

Run with the base powered, plugged in and the stick released::

    WFE_HARDWARE=1 uv run pytest tests/test_sdl_hardware.py -v --log-cli-level=INFO

The stick's input bindings come from ``WFE_PITCH_AXIS`` / ``WFE_ROLL_AXIS``
(default 1 / 0) and ``WFE_PITCH_INVERT`` / ``WFE_ROLL_INVERT`` (``1`` to
invert, default 0); the same bindings build the input and the haptic axis
map, so index and sign are verified together. ``WFE_REFRESH_EVERY_TICK=1``
builds the backend with ``refresh_every_tick=True`` (update and re-run every
persistent effect every tick) to A/B it against the default, which uploads
only on change and re-runs at half the effect length. The test measures, in
frame space through ``CompositeInput``:

1. a spring at centre +0.5 (coefficient 0.3) held 2 s brings pitch to
   +0.5 +/- 0.15 -- the physical direction depends on the binding;
2. a positive pitch pulse (0.3 for 0.2 s) moves pitch in the + direction;
3. a 5.5 Hz sine (magnitude 0.2) is then held 2 s to be felt (a smooth buzz,
   not a rattle); its pitch range is logged, not asserted.
"""

import logging
import os
import time
from collections.abc import Sequence
from statistics import mean

import pytest

from wardogs_flight_eng.engine.commands import (
    Axis,
    Command,
    PulseCommand,
    SineCommand,
    SpringCommand,
)
from wardogs_flight_eng.engine.device_map import (
    AxisBinding,
    Calibration,
    DeviceMap,
    DeviceRef,
)
from wardogs_flight_eng.inputs.composite import CompositeInput
from wardogs_flight_eng.inputs.sdl_device import enumerate_devices, open_by_guid
from wardogs_flight_eng.outputs.haptic_axes import HapticAxisMap
from wardogs_flight_eng.outputs.sdl_haptic import SdlHapticBackend, probe_primitives

pytestmark = pytest.mark.skipif(
    os.environ.get("WFE_HARDWARE") != "1",
    reason="real force-feedback hardware test; set WFE_HARDWARE=1 to run",
)

log = logging.getLogger(__name__)

TICK_S = 0.01
HOLD_S = 2.0
SPRING = SpringCommand(Axis.PITCH, 0.5, 0.3, 0.0)
CENTER_TOLERANCE = 0.15
PULSE = PulseCommand(Axis.PITCH, 0.3, 0.2)
MIN_PULSE_DELTA = 0.02
SINE = SineCommand(Axis.PITCH, 5.5, 0.2)


def _binding(name: str, default_axis: int) -> AxisBinding:
    axis = int(os.environ.get(f"WFE_{name}_AXIS", default_axis))
    invert = os.environ.get(f"WFE_{name}_INVERT", "0") == "1"
    return AxisBinding(device="stick", axis=axis, invert=invert)


def _device_map(guid: str, pitch: AxisBinding, roll: AxisBinding) -> DeviceMap:
    spare = AxisBinding(device="stick", axis=0)
    return DeviceMap(
        devices={"stick": DeviceRef(guid=guid, product=None)},
        axes={"pitch": pitch, "roll": roll, "collective": spare, "pedals": spare},
        buttons={},
        calibration=Calibration(),
    )


def _run(
    backend: SdlHapticBackend,
    source: CompositeInput,
    start: float,
    seconds: float,
    first: Sequence[Command] = (),
    every: Sequence[Command] = (SPRING,),
) -> list[float]:
    """Apply ``first`` + ``every`` once, then ``every`` per tick; read pitch."""
    readings: list[float] = []
    commands = [*first, *every]
    end = time.perf_counter() + seconds
    while (now := time.perf_counter()) < end:
        backend.apply(now - start, commands)
        commands = list(every)
        readings.append(source.read().pitch)
        time.sleep(TICK_S)
    return readings


def _measure(backend: SdlHapticBackend, source: CompositeInput) -> None:
    start = time.perf_counter()
    held = _run(backend, source, start, HOLD_S)[-1]
    log.info("spring centre +0.5: pitch reads %+.3f", held)
    assert abs(held - SPRING.center) <= CENTER_TOLERANCE

    pushed = _run(backend, source, start, PULSE.duration_s, first=[PULSE])
    delta = mean(pushed[len(pushed) // 2 :]) - held
    log.info("pulse +%.1f: pitch delta %+.3f", PULSE.magnitude, delta)
    assert delta > MIN_PULSE_DELTA

    buzz = _run(backend, source, start, HOLD_S, every=(SPRING, SINE))
    log.info("sine %.1f Hz: pitch range %.3f", SINE.frequency_hz, max(buzz) - min(buzz))


def test_first_haptic_device_conforms() -> None:
    haptic = [info for info in enumerate_devices() if info.has_haptic]
    assert haptic, "no force-feedback device found"
    guid = haptic[0].guid
    report = probe_primitives(guid)
    assert report.spring and report.spring_center_moves
    assert report.sine and report.constant

    pitch, roll = _binding("PITCH", 1), _binding("ROLL", 0)
    device = open_by_guid(guid)
    source = CompositeInput(_device_map(guid, pitch, roll), {"stick": device})
    axis_map = HapticAxisMap.from_bindings(pitch=pitch, roll=roll)
    backend = SdlHapticBackend(
        device,
        persistent_length_s=1.0,
        axis_map=axis_map,
        refresh_every_tick=os.environ.get("WFE_REFRESH_EVERY_TICK") == "1",
    )
    try:
        _measure(backend, source)
        backend.all_off()
    finally:
        backend.close()
        device.close()
