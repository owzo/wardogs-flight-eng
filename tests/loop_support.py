"""Clocks, scripted inputs and failing backends for the runtime-loop tests."""

from collections.abc import Sequence

from backends_support import RecordingBackend

from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.commands import Command
from wardogs_flight_eng.engine.device_map import (
    AxisBinding,
    ButtonBinding,
    Calibration,
    DeviceMap,
    DeviceRef,
)
from wardogs_flight_eng.engine.frame import Button
from wardogs_flight_eng.engine.profile import PROFILES_DIR, load_profile
from wardogs_flight_eng.engine.synth import FlightEngine
from wardogs_flight_eng.inputs.composite import CompositeInput
from wardogs_flight_eng.inputs.simulated import SimulatedDevice

Devices = dict[str, SimulatedDevice]

PROFILE_CYCLE_IDX = 0
ALL_OFF_IDX = 1


class StepClock:
    """Returns the scripted times in order, then repeats the last one."""

    def __init__(self, times: Sequence[float]) -> None:
        self._times = list(times)
        self._next = 0

    def __call__(self) -> float:
        value = self._times[min(self._next, len(self._times) - 1)]
        self._next += 1
        return value


class TickClock:
    """Advances ``step`` seconds per call (the loop reads the clock twice a tick)."""

    def __init__(self, step: float) -> None:
        self._now = 0.0
        self._step = step

    def __call__(self) -> float:
        self._now += self._step
        return self._now


class ButtonScript:
    """A ``sleep`` stand-in that records sleeps and sets grip buttons per tick.

    ``presses[n]`` is the set of grip buttons held on tick ``n`` (0-based,
    the last entry repeats); tick 0 is set up front, later ticks after each
    sleep.
    """

    def __init__(self, devices: Devices, presses: list[set[int]]) -> None:
        self._grip = devices["grip"]
        self._presses = presses
        self._tick = 0
        self.sleeps: list[float] = []
        self._set(0)

    def _set(self, tick: int) -> None:
        held = self._presses[min(tick, len(self._presses) - 1)]
        for index in range(self._grip.button_count):
            self._grip.buttons[index] = index in held

    def __call__(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._tick += 1
        self._set(self._tick)


class FailingApplyBackend(RecordingBackend):
    def apply(self, t: float, commands: Sequence[Command]) -> None:
        raise OSError("device write failed")


class FailingAllOffBackend(RecordingBackend):
    def all_off(self) -> None:
        super().all_off()
        raise OSError("stop-all failed")


def make_engine(name: str) -> FlightEngine:
    return FlightEngine(load_profile(PROFILES_DIR / f"{name}.json"), load_constants())


def make_devices() -> Devices:
    return {
        "stick": SimulatedDevice("stick", axis_count=2),
        "grip": SimulatedDevice("grip", button_count=4),
        "coll": SimulatedDevice("coll", axis_count=1),
        "ped": SimulatedDevice("ped", axis_count=1),
    }


def make_source(devices: Devices) -> CompositeInput:
    """Every axis bound; PROFILE_CYCLE and ALL_OFF on the grip."""
    grip = {
        Button.PROFILE_CYCLE: PROFILE_CYCLE_IDX,
        Button.ALL_OFF: ALL_OFF_IDX,
    }
    device_map = DeviceMap(
        devices={name: DeviceRef(guid=f"sim-{name}", product=None) for name in devices},
        axes={
            "pitch": AxisBinding(device="stick", axis=0),
            "roll": AxisBinding(device="stick", axis=1),
            "collective": AxisBinding(device="coll", axis=0),
            "pedals": AxisBinding(device="ped", axis=0),
        },
        buttons={b: ButtonBinding(device="grip", button=i) for b, i in grip.items()},
        calibration=Calibration(),
    )
    return CompositeInput(device_map, devices)
