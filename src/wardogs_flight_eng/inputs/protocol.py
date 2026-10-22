"""Input device contract and the errors the input layer raises."""

from typing import Protocol


class InputConfigError(ValueError):
    """The device map or scenario does not match the devices that are present."""


class DeviceLostError(RuntimeError):
    """A bound device stopped reporting (unplugged or reset) mid-session."""


class InputDevice(Protocol):
    """One physical (or simulated) device exposing raw axes and buttons.

    ``poll`` refreshes the device's state; ``axis`` returns the raw reading
    in -1..1 and ``button`` the pressed state. ``alive`` turns False once the
    device is gone.
    """

    name: str
    guid: str
    axis_count: int
    button_count: int
    alive: bool

    def poll(self) -> None: ...

    def axis(self, index: int) -> float: ...

    def button(self, index: int) -> bool: ...
