"""AB9 conformance check on real hardware; skipped unless ``WFE_HARDWARE=1``.

Run with the base powered and plugged in: ``WFE_HARDWARE=1 uv run pytest
tests/test_sdl_hardware.py -v``. It probes the four primitives, then holds a
spring at centre 0.5 (coefficient 0.3) for 2 s: the stick should move to and
hold half-forward deflection, then go limp.
"""

import os
import time

import pytest

from wardogs_flight_eng.engine.commands import Axis, SpringCommand
from wardogs_flight_eng.inputs.sdl_device import enumerate_devices, open_by_guid
from wardogs_flight_eng.outputs.sdl_haptic import SdlHapticBackend, probe_primitives

pytestmark = pytest.mark.skipif(
    os.environ.get("WFE_HARDWARE") != "1",
    reason="real force-feedback hardware test; set WFE_HARDWARE=1 to run",
)

HOLD_S = 2.0
TICK_S = 0.01


def test_first_haptic_device_supports_every_primitive() -> None:
    haptic = [info for info in enumerate_devices() if info.has_haptic]
    assert haptic, "no force-feedback device found"
    guid = haptic[0].guid

    report = probe_primitives(guid)
    assert report.spring and report.spring_center_moves
    assert report.sine and report.constant

    device = open_by_guid(guid)
    backend = SdlHapticBackend(device, persistent_length_s=1.0)
    try:
        spring = [SpringCommand(Axis.PITCH, 0.5, 0.3, 0.0)]
        start = time.perf_counter()
        while (now := time.perf_counter()) - start < HOLD_S:
            backend.apply(now - start, spring)
            time.sleep(TICK_S)
        backend.all_off()
    finally:
        backend.close()
        device.close()
