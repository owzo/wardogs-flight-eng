"""Profile device map: which physical device axis or button feeds each channel.

Shipped profiles leave every map empty; ``list-devices`` and ``calibrate``
fill them for the owner's hardware.
"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wardogs_flight_eng.engine.frame import Button

AxisName = Literal["pitch", "roll", "collective", "pedals"]


class ProfileModel(BaseModel):
    """Base for every profile section: immutable, unknown keys rejected."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DeviceRef(ProfileModel):
    """A physical device identified by SDL GUID and/or product name."""

    guid: str | None
    product: str | None


class AxisBinding(ProfileModel):
    """One device axis feeding a logical channel."""

    device: str
    axis: int = Field(ge=0)
    invert: bool = False


class ButtonBinding(ProfileModel):
    """One device button feeding a logical button."""

    device: str
    button: int = Field(ge=0)


class Calibration(ProfileModel):
    """Raw device readings at the collective's ends and the pedals' centre."""

    collective_bottom_raw: float = -1
    collective_top_raw: float = 1
    pedals_center_raw: float = 0


class DeviceMap(ProfileModel):
    """Device aliases, channel bindings and calibration for one hardware set."""

    devices: dict[str, DeviceRef]
    axes: dict[AxisName, AxisBinding]
    buttons: dict[Button, ButtonBinding]
    calibration: Calibration

    @model_validator(mode="after")
    def _bindings_name_known_devices(self) -> Self:
        bindings: list[tuple[str, str]] = [
            *((f"axes.{k}", b.device) for k, b in self.axes.items()),
            *((f"buttons.{k}", b.device) for k, b in self.buttons.items()),
        ]
        for where, device in bindings:
            if device not in self.devices:
                raise ValueError(f"{where} names unknown device {device!r}")
        return self
