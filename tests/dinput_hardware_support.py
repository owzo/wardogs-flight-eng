"""Helpers for the DirectInput hardware test: the rig and the frequency read.

``rig`` opens the base through the real adapter (``WFE_SDL_GUID`` matched
as ``run`` matches it, else the first force-feedback instance) with the
``WFE_*_AXIS`` / ``WFE_*_INVERT`` bindings; ``run`` drives it on one clock
for the backend's whole life; ``measured_frequency`` reads a pitch trace.
"""

import contextlib
import math
import os
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from statistics import mean, pstdev

from wardogs_flight_eng.engine.commands import Command
from wardogs_flight_eng.engine.device_map import (
    AxisBinding,
    Calibration,
    DeviceMap,
    DeviceRef,
)
from wardogs_flight_eng.inputs.composite import CompositeInput
from wardogs_flight_eng.inputs.dinput_device import (
    DInputJoystick,
    ff_actuator_check,
    open_dinput_instance,
    open_dinput_joystick,
)
from wardogs_flight_eng.inputs.dinput_real import RealDirectInput
from wardogs_flight_eng.outputs.dinput_haptic import DInputHapticBackend
from wardogs_flight_eng.outputs.haptic_axes import HapticAxisMap

TICK_S = 0.01
HYSTERESIS = 0.3  # of the detrended trace's standard deviation

Trace = tuple[list[float], list[float]]  # (times, pitch readings)


@dataclass(frozen=True, slots=True)
class Rig:
    """The backend and input over one opened base; ``start`` is its clock's 0."""

    backend: DInputHapticBackend
    source: CompositeInput
    start: float


def measured_frequency(
    times: Sequence[float], trace: Sequence[float], nominal_hz: float
) -> float:
    """Zero-crossing frequency of ``trace``.

    The moving average over one nominal period (which cancels a sine of that
    period) is subtracted to remove the stick's drift; a crossing counts only
    once the value leaves a hysteresis band, so noise cannot add crossings.
    """
    rate = (len(trace) - 1) / (times[-1] - times[0])
    half = max(1, round(rate / nominal_hz)) // 2
    detrended = [
        trace[i] - mean(trace[i - half : i + half + 1])
        for i in range(half, len(trace) - half)
    ]
    band = HYSTERESIS * pstdev(detrended)
    crossings, side = 0, 0
    for value in detrended:
        if abs(value) <= band:
            continue
        current = 1 if value > 0 else -1
        crossings += side not in (0, current)
        side = current
    return crossings / (2 * (len(detrended) - 1) / rate)


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


def _open_base(api: RealDirectInput) -> DInputJoystick:
    guid = os.environ.get("WFE_SDL_GUID")
    if guid:
        return open_dinput_joystick(api, guid)
    found = [info for info in api.enumerate_devices() if info.force_feedback]
    assert found, "no force-feedback DirectInput device found"
    return open_dinput_instance(api, found[0], found[0].instance_guid)


@contextlib.contextmanager
def rig() -> Iterator[Rig]:
    """The base opened through the real adapter, its backend and input."""
    pitch, roll = _binding("PITCH", 1), _binding("ROLL", 0)
    axis_map = HapticAxisMap.from_bindings(pitch=pitch, roll=roll)
    api = RealDirectInput()
    try:
        joystick = _open_base(api)
        backend = DInputHapticBackend(joystick, 1.0, axis_map=axis_map)
    except BaseException:
        api.close()  # also releases a device opened before the failure
        raise
    try:
        ff_actuator_check(joystick, axis_map)
        device_map = _device_map(joystick.guid, pitch, roll)
        source = CompositeInput(device_map, {"stick": joystick})
        yield Rig(backend, source, time.perf_counter())
    finally:
        backend.close()


def run(
    base: Rig,
    seconds: float,
    every: Callable[[float], Sequence[Command]],
    first: Sequence[Command] = (),
    tick_s: float = TICK_S,
) -> Trace:
    """Apply ``first`` + ``every(fraction)`` once, then ``every`` per tick."""
    times: list[float] = []
    readings: list[float] = []
    begin = time.perf_counter()
    commands = [*first, *every(0.0)]
    while (now := time.perf_counter()) - begin < seconds:
        base.backend.apply(now - base.start, commands)
        times.append(now)
        readings.append(base.source.read().pitch)
        time.sleep(tick_s)
        fraction = min(1.0, (time.perf_counter() - begin) / seconds)
        commands = list(every(fraction))
    return times, readings


def steady(*commands: Command) -> Callable[[float], Sequence[Command]]:
    return lambda _fraction: commands


def sin_turns(cycles: float) -> float:
    """``sin`` of ``cycles`` whole turns."""
    return math.sin(2 * math.pi * cycles)
