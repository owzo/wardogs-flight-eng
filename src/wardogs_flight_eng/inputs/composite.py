"""Compose any number of input devices into the engine's logical channels."""

from collections.abc import Mapping

from wardogs_flight_eng.engine.device_map import AxisBinding, AxisName, DeviceMap
from wardogs_flight_eng.engine.frame import Button, ControlFrame
from wardogs_flight_eng.inputs.protocol import (
    DeviceLostError,
    InputConfigError,
    InputDevice,
)

AXIS_CHANNELS: tuple[AxisName, ...] = ("pitch", "roll", "collective", "pedals")


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class CompositeInput:
    """Reads bound devices and returns one calibrated ``ControlFrame`` per tick.

    The device map is checked against the devices once, at construction, so a
    wrong index fails with the logical channel named rather than mid-flight.
    """

    def __init__(self, device_map: DeviceMap, devices: Mapping[str, InputDevice]):
        self._map = device_map
        self._devices = devices
        self._validate()

    def _validate(self) -> None:
        cal = self._map.calibration
        if cal.collective_bottom_raw == cal.collective_top_raw:
            raise InputConfigError(
                "collective calibration has identical bottom and top raw values"
            )
        for channel in AXIS_CHANNELS:
            binding = self._map.axes.get(channel)
            if binding is None:
                raise InputConfigError(f"axis channel {channel!r} has no binding")
            device = self._device_for(channel, binding.device)
            if binding.axis >= device.axis_count:
                raise InputConfigError(
                    f"axis channel {channel!r}: device {binding.device!r} has "
                    f"{device.axis_count} axes, no axis {binding.axis}"
                )
        for button, bound in self._map.buttons.items():
            device = self._device_for(button.value, bound.device)
            if bound.button >= device.button_count:
                raise InputConfigError(
                    f"button channel {button.value!r}: device {bound.device!r} has "
                    f"{device.button_count} buttons, no button {bound.button}"
                )

    def _device_for(self, channel: str, name: str) -> InputDevice:
        device = self._devices.get(name)
        if device is None:
            raise InputConfigError(
                f"channel {channel!r} is bound to missing device {name!r}"
            )
        return device

    def read(self) -> ControlFrame:
        """Poll every device and build the calibrated frame for this tick."""
        for name, device in self._devices.items():
            device.poll()
            if not device.alive:
                raise DeviceLostError(f"input device {name!r} was lost")
        cal = self._map.calibration
        span = cal.collective_top_raw - cal.collective_bottom_raw
        collective = (self._raw("collective") - cal.collective_bottom_raw) / span
        return ControlFrame(
            pitch=_clamp(self._signed("pitch"), -1.0, 1.0),
            roll=_clamp(self._signed("roll"), -1.0, 1.0),
            collective=_clamp(collective, 0.0, 1.0),
            pedals=_clamp(self._raw("pedals") - cal.pedals_center_raw, -1.0, 1.0),
            held=self._held(),
        )

    def _binding(self, channel: AxisName) -> AxisBinding:
        return self._map.axes[channel]

    def _raw(self, channel: AxisName) -> float:
        binding = self._binding(channel)
        return self._devices[binding.device].axis(binding.axis)

    def _signed(self, channel: AxisName) -> float:
        raw = self._raw(channel)
        return -raw if self._binding(channel).invert else raw

    def _held(self) -> frozenset[Button]:
        return frozenset(
            button
            for button, bound in self._map.buttons.items()
            if self._devices[bound.device].button(bound.button)
        )
