"""Where each frame-space stick axis lives on the force-feedback device.

The engine works in frame space: the stick axes as ``CompositeInput``
reports them, after each binding's ``invert``. SDL haptic effects act in
device space. ``HapticAxisMap`` carries, per ``Axis``, the haptic axis index
(the bound joystick axis, assumed to be the same index on the haptic side)
and the sign that undoes the binding's inversion.
"""

from dataclasses import dataclass

from wardogs_flight_eng.engine.commands import Axis
from wardogs_flight_eng.engine.device_map import AxisBinding

HAPTIC_AXES = 3  # SDL direction and condition arrays hold X, Y, Z


@dataclass(frozen=True, slots=True)
class HapticAxis:
    """One stick axis on the device: its haptic index and frame->device sign."""

    haptic_index: int
    sign: float


@dataclass(frozen=True, slots=True)
class HapticAxisMap:
    """Frame-space ``Axis`` -> device-space ``HapticAxis`` for pitch and roll."""

    pitch: HapticAxis
    roll: HapticAxis

    def __post_init__(self) -> None:
        for name, entry in (("pitch", self.pitch), ("roll", self.roll)):
            if not 0 <= entry.haptic_index < HAPTIC_AXES:
                raise ValueError(
                    f"{name}: haptic index {entry.haptic_index} outside 0..2"
                )
            if entry.sign not in (1.0, -1.0):
                raise ValueError(f"{name}: haptic sign must be +1 or -1")
        if self.pitch.haptic_index == self.roll.haptic_index:
            raise ValueError(
                f"pitch and roll share haptic axis {self.pitch.haptic_index}"
            )

    def __getitem__(self, axis: Axis) -> HapticAxis:
        return self.pitch if axis is Axis.PITCH else self.roll

    @classmethod
    def from_bindings(cls, pitch: AxisBinding, roll: AxisBinding) -> "HapticAxisMap":
        """Build from the profile's ``device_map.axes["pitch"]`` and ``["roll"]``."""
        return cls(pitch=_entry(pitch), roll=_entry(roll))


def _entry(binding: AxisBinding) -> HapticAxis:
    return HapticAxis(binding.axis, -1.0 if binding.invert else 1.0)
