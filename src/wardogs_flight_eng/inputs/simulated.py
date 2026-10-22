"""Simulated input devices and a scripted scenario, so no hardware is needed."""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from wardogs_flight_eng.engine.device_map import DeviceMap
from wardogs_flight_eng.inputs.protocol import InputConfigError, InputDevice

_TARGET = re.compile(r"^(?P<device>[^.]+)\.(?P<kind>axis|button)(?P<index>\d+)$")


class SimulatedDevice(InputDevice):
    """In-memory device whose ``axes`` and ``buttons`` are set directly."""

    def __init__(
        self,
        name: str,
        *,
        axis_count: int = 0,
        button_count: int = 0,
        guid: str | None = None,
    ) -> None:
        self.name = name
        self.guid = guid if guid is not None else f"sim-{name}"
        self.axis_count = axis_count
        self.button_count = button_count
        self.axes: list[float] = [0.0] * axis_count
        self.buttons: list[bool] = [False] * button_count
        self.alive = True

    def poll(self) -> None:
        """Nothing to refresh: state is whatever the caller last set."""

    def axis(self, index: int) -> float:
        return self.axes[index]

    def button(self, index: int) -> bool:
        return self.buttons[index]


@dataclass(frozen=True, slots=True)
class _Step:
    t: float
    assignments: tuple[tuple[str, int, str, float | bool], ...]


class Scenario:
    """A timed script of device changes plus the device map that reads them."""

    def __init__(
        self,
        rate_hz: float,
        device_map: DeviceMap,
        devices: dict[str, SimulatedDevice],
        steps: list[_Step],
    ) -> None:
        self.rate_hz = rate_hz
        self.device_map = device_map
        self.devices = devices
        self._steps = steps
        self._next = 0
        self.duration_s = steps[-1].t if steps else 0.0

    @classmethod
    def load(cls, path: Path) -> "Scenario":
        """Parse a scenario file, validating the map, targets and step order."""
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        try:
            device_map = DeviceMap.model_validate(raw["device_map"])
            devices = {
                name: SimulatedDevice(
                    name, axis_count=spec["axes"], button_count=spec["buttons"]
                )
                for name, spec in raw["devices"].items()
            }
            rate_hz = float(raw["rate_hz"])
            raw_steps = raw["steps"]
        except (KeyError, TypeError, ValidationError) as exc:
            raise InputConfigError(f"invalid scenario {path}: {exc}") from exc
        return cls(rate_hz, device_map, devices, _parse_steps(raw_steps, devices))

    def apply_until(self, t: float) -> None:
        """Apply, once and in order, every step scheduled at or before ``t``."""
        while self._next < len(self._steps) and self._steps[self._next].t <= t:
            self._apply(self._steps[self._next])
            self._next += 1

    def _apply(self, step: _Step) -> None:
        for device, index, kind, value in step.assignments:
            target = self.devices[device]
            if kind == "axis":
                target.axes[index] = float(value)
            else:
                target.buttons[index] = bool(value)


def _parse_steps(
    raw_steps: list[dict[str, Any]], devices: dict[str, SimulatedDevice]
) -> list[_Step]:
    steps: list[_Step] = []
    for raw in raw_steps:
        t = float(raw["t"])
        if steps and t < steps[-1].t:
            raise InputConfigError(f"scenario steps must be sorted by t (at {t})")
        assignments = tuple(
            _parse_target(key, value, devices) for key, value in raw["set"].items()
        )
        steps.append(_Step(t, assignments))
    return steps


def _parse_target(
    key: str, value: float | bool, devices: dict[str, SimulatedDevice]
) -> tuple[str, int, str, float | bool]:
    match = _TARGET.match(key)
    if match is None or match["device"] not in devices:
        raise InputConfigError(f"scenario target {key!r} names no known device")
    device = devices[match["device"]]
    kind, index = match["kind"], int(match["index"])
    limit = device.axis_count if kind == "axis" else device.button_count
    if index >= limit:
        raise InputConfigError(f"scenario target {key!r} is out of range")
    return match["device"], index, kind, value
