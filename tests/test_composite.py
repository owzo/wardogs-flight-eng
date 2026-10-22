"""CompositeInput: device-map validation, calibration and device loss."""

import pytest

from wardogs_flight_eng.engine.device_map import AxisName
from wardogs_flight_eng.engine.frame import Button
from wardogs_flight_eng.engine.profile import (
    AxisBinding,
    ButtonBinding,
    Calibration,
    DeviceMap,
    DeviceRef,
)
from wardogs_flight_eng.inputs.composite import CompositeInput
from wardogs_flight_eng.inputs.protocol import DeviceLostError, InputConfigError
from wardogs_flight_eng.inputs.simulated import SimulatedDevice

Devices = dict[str, SimulatedDevice]

DEFAULT_AXES: dict[AxisName, AxisBinding] = {
    "pitch": AxisBinding(device="stick", axis=0),
    "roll": AxisBinding(device="stick", axis=1),
    "collective": AxisBinding(device="coll", axis=0),
    "pedals": AxisBinding(device="ped", axis=0),
}


def device_map(
    axes: dict[AxisName, AxisBinding] | None = None,
    buttons: dict[str, tuple[str, int]] | None = None,
    calibration: Calibration | None = None,
) -> DeviceMap:
    """Build a map over stick/grip/coll/ped with every axis bound by default."""
    return DeviceMap(
        devices={
            name: DeviceRef(guid=f"sim-{name}", product=None)
            for name in ("stick", "grip", "coll", "ped")
        },
        axes=axes if axes is not None else dict(DEFAULT_AXES),
        buttons={
            Button(channel): ButtonBinding(device=dev, button=index)
            for channel, (dev, index) in (buttons or {}).items()
        },
        calibration=calibration or Calibration(),
    )


def stick() -> SimulatedDevice:
    return SimulatedDevice("stick", axis_count=2)


def coll() -> SimulatedDevice:
    return SimulatedDevice("coll", axis_count=1)


def ped() -> SimulatedDevice:
    return SimulatedDevice("ped", axis_count=1)


def grip(button_count: int = 8) -> SimulatedDevice:
    return SimulatedDevice("grip", button_count=button_count)


@pytest.fixture
def devices() -> Devices:
    return {"stick": stick(), "grip": grip(), "coll": coll(), "ped": ped()}


def test_missing_button_index_fails_at_construction() -> None:  # Review Focus 1
    dm = device_map(buttons={"trim_lock": ("grip", 40)})
    grip32 = SimulatedDevice("grip", button_count=32)
    with pytest.raises(InputConfigError, match="trim_lock"):
        CompositeInput(
            dm, {"grip": grip32, "stick": stick(), "coll": coll(), "ped": ped()}
        )


def test_missing_device_fails_at_construction_naming_channel(devices: Devices) -> None:
    dm = device_map(buttons={"fire": ("grip", 0)})
    del devices["grip"]
    with pytest.raises(InputConfigError, match="fire"):
        CompositeInput(dm, devices)


def test_axis_index_out_of_range_names_channel(devices: Devices) -> None:
    axes = {**DEFAULT_AXES, "roll": AxisBinding(device="stick", axis=5)}
    with pytest.raises(InputConfigError, match="roll"):
        CompositeInput(device_map(axes=axes), devices)


def test_unbound_axis_names_channel(devices: Devices) -> None:
    axes = DEFAULT_AXES.copy()
    del axes["pedals"]
    with pytest.raises(InputConfigError, match="pedals"):
        CompositeInput(device_map(axes=axes), devices)


def test_degenerate_collective_calibration_rejected(devices: Devices) -> None:
    cal = Calibration(collective_bottom_raw=0.5, collective_top_raw=0.5)
    with pytest.raises(InputConfigError, match="collective"):
        CompositeInput(device_map(calibration=cal), devices)


def test_inverted_collective_calibration(devices: Devices) -> None:  # Review Focus 2
    cal = Calibration(collective_bottom_raw=0.9, collective_top_raw=-0.8)
    c = CompositeInput(device_map(calibration=cal), devices)
    devices["coll"].axes[0] = 0.9
    assert c.read().collective == 0.0
    devices["coll"].axes[0] = -0.8
    assert c.read().collective == 1.0


def test_collective_normalised_and_clamped(devices: Devices) -> None:
    c = CompositeInput(device_map(), devices)
    devices["coll"].axes[0] = 0.0
    assert c.read().collective == pytest.approx(0.5)
    devices["coll"].axes[0] = -1.0
    assert c.read().collective == 0.0
    devices["coll"].axes[0] = 1.0
    assert c.read().collective == 1.0


def test_collective_beyond_calibrated_range_is_clamped(devices: Devices) -> None:
    cal = Calibration(collective_bottom_raw=-0.5, collective_top_raw=0.5)
    c = CompositeInput(device_map(calibration=cal), devices)
    devices["coll"].axes[0] = -1.0
    assert c.read().collective == 0.0
    devices["coll"].axes[0] = 1.0
    assert c.read().collective == 1.0


def test_pedals_centred_and_clamped(devices: Devices) -> None:
    cal = Calibration(pedals_center_raw=0.25)
    c = CompositeInput(device_map(calibration=cal), devices)
    devices["ped"].axes[0] = 0.25
    assert c.read().pedals == 0.0
    devices["ped"].axes[0] = 0.75
    assert c.read().pedals == pytest.approx(0.5)
    devices["ped"].axes[0] = -1.0
    assert c.read().pedals == -1.0


def test_pedals_clamped_when_offset_overflows(devices: Devices) -> None:
    cal = Calibration(pedals_center_raw=-0.5)
    c = CompositeInput(device_map(calibration=cal), devices)
    devices["ped"].axes[0] = 1.0
    assert c.read().pedals == 1.0


def test_invert_negates_pitch_and_roll(devices: Devices) -> None:
    axes = {
        **DEFAULT_AXES,
        "pitch": AxisBinding(device="stick", axis=0, invert=True),
        "roll": AxisBinding(device="stick", axis=1, invert=True),
    }
    c = CompositeInput(device_map(axes=axes), devices)
    devices["stick"].axes[:] = [0.4, -0.7]
    frame = c.read()
    assert (frame.pitch, frame.roll) == (-0.4, 0.7)


def test_held_reports_pressed_bound_buttons(devices: Devices) -> None:
    dm = device_map(buttons={"fire": ("grip", 2), "reload": ("grip", 3)})
    c = CompositeInput(dm, devices)
    assert c.read().held == frozenset()
    devices["grip"].buttons[2] = True
    assert c.read().held == frozenset({Button.FIRE})


def test_device_lost_raises(devices: Devices) -> None:
    c = CompositeInput(device_map(), devices)
    devices["ped"].alive = False
    with pytest.raises(DeviceLostError, match="ped"):
        c.read()
