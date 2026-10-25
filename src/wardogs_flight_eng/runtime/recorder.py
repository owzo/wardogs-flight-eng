"""Turn raw device snapshots into a scenario document ``Scenario.load`` reads.

Pure: no SDL, no files. The first step holds every axis and button; later
steps hold only what changed, an axis counting as changed once it moves at
least ``min_change`` from the value last written for it (hysteresis, so a
noisy axis cannot write a step every tick). The last step is empty and
marks the recording's end. Step times are written unrounded: a replay's
tick ``n`` reads ``n / rate_hz``, and JSON floats round-trip exactly, so a
step recorded at that time is applied on that same tick.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from wardogs_flight_eng.engine.device_map import DeviceMap

AXIS_DECIMALS = 3
_MOVE_DECIMALS = 9
"""A move is rounded before the ``min_change`` test, so float noise in
``0.105 - 0.1`` cannot decide it."""

Value = float | bool


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    """One device's raw axes (-1..1) and buttons at one instant."""

    axes: tuple[float, ...]
    buttons: tuple[bool, ...]


def replay_end(ticks: int, rate_hz: float) -> float:
    """The closing ``t`` for ``ticks``: ``int(t * rate_hz)`` is exactly ``ticks``.

    ``ticks / rate_hz`` can multiply back to just under ``ticks`` (e.g. 123
    at 30 Hz), which a replay truncating ``duration * rate`` would read as
    one tick fewer; one ulp up is always enough.
    """
    end = ticks / rate_hz
    if int(end * rate_hz) < ticks:
        end = math.nextafter(end, math.inf)
    return end


def _values(snapshot: Mapping[str, DeviceSnapshot]) -> dict[str, Value]:
    values: dict[str, Value] = {}
    for alias, device in snapshot.items():
        for index, axis in enumerate(device.axes):
            values[f"{alias}.axis{index}"] = round(float(axis), AXIS_DECIMALS)
        for index, button in enumerate(device.buttons):
            values[f"{alias}.button{index}"] = bool(button)
    return values


class ScenarioRecorder:
    """Accumulates change-only steps between ``begin`` and ``finish``."""

    def __init__(self, rate_hz: float, min_change: float) -> None:
        self._rate_hz = rate_hz
        self._min_change = min_change
        self._shapes: dict[str, dict[str, int]] = {}
        self._written: dict[str, Value] = {}
        self._steps: list[dict[str, Any]] = []

    @property
    def step_count(self) -> int:
        return len(self._steps)

    def begin(self, t: float, snapshot: Mapping[str, DeviceSnapshot]) -> None:
        """Record every axis and button of ``snapshot`` as the first step."""
        self._shapes = {
            alias: {"axes": len(device.axes), "buttons": len(device.buttons)}
            for alias, device in snapshot.items()
        }
        self._written = _values(snapshot)
        self._steps = [{"t": float(t), "set": dict(self._written)}]

    def observe(self, t: float, snapshot: Mapping[str, DeviceSnapshot]) -> None:
        """Add one step holding every change since the last written values."""
        changed = {
            key: value
            for key, value in _values(snapshot).items()
            if self._is_change(key, value)
        }
        if not changed:
            return
        self._written.update(changed)
        self._steps.append({"t": float(t), "set": changed})

    def _is_change(self, key: str, value: Value) -> bool:
        last = self._written[key]
        if isinstance(value, bool):
            return value != last
        moved = round(abs(value - float(last)), _MOVE_DECIMALS)
        return moved > 0 and moved >= self._min_change

    def finish(self, t: float, device_map: DeviceMap) -> dict[str, Any]:
        """Close with an empty step at ``t``; return the scenario document."""
        self._steps.append({"t": float(t), "set": {}})
        return {
            "rate_hz": self._rate_hz,
            "device_map": device_map.model_dump(mode="json"),
            "devices": {alias: dict(shape) for alias, shape in self._shapes.items()},
            "steps": [dict(step) for step in self._steps],
        }
