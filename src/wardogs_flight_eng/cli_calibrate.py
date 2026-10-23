"""``calibrate``: record the collective's ends and the pedals' centre."""

import argparse
from typing import Final

from wardogs_flight_eng.cli_console import EXIT_OK, CliContext, CliError
from wardogs_flight_eng.cli_devices import close_devices, open_devices
from wardogs_flight_eng.cli_profiles import load_checked_profile, write_calibration
from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.device_map import AxisBinding, AxisName, DeviceMap
from wardogs_flight_eng.engine.profile import Calibration
from wardogs_flight_eng.inputs.protocol import DeviceLostError
from wardogs_flight_eng.inputs.sdl_device import SdlDevice

READING_DECIMALS: Final = 4

STEPS: Final[tuple[tuple[str, AxisName, str], ...]] = (
    ("collective_bottom_raw", "collective", "Collective fully down, then press Enter"),
    ("collective_top_raw", "collective", "Collective fully up, then press Enter"),
    ("pedals_center_raw", "pedals", "Pedals centred, then press Enter"),
)


def _binding(device_map: DeviceMap, channel: AxisName) -> AxisBinding:
    binding = device_map.axes.get(channel)
    if binding is None:
        raise CliError(
            f"device_map.axes.{channel}: not bound; bind it (see "
            "`list-devices --live`) before calibrating"
        )
    return binding


def _sample(ctx: CliContext, device: SdlDevice, axis: int, prompt: str) -> float:
    """Prompt, wait for Enter, then read the raw (uninverted) axis."""
    ctx.console.line(prompt)
    if ctx.stdin.readline() == "":
        raise CliError("calibration aborted: input closed before Enter")
    device.poll()
    if not device.alive:
        raise DeviceLostError(f"device {device.name!r} was lost during calibration")
    reading = round(device.axis(axis), READING_DECIMALS)
    ctx.console.line(f"  read {reading:+.4f}")
    return reading


def _readings(
    ctx: CliContext, device_map: DeviceMap, devices: dict[str, SdlDevice]
) -> dict[str, float]:
    readings: dict[str, float] = {}
    for field, channel, prompt in STEPS:
        binding = _binding(device_map, channel)
        device = devices[binding.device]
        readings[field] = _sample(ctx, device, binding.axis, prompt)
    return readings


def calibrate_command(args: argparse.Namespace, ctx: CliContext) -> int:
    """Sample three positions, then rewrite only the profile's calibration."""
    profile = load_checked_profile(args.profile, load_constants())
    device_map = profile.device_map
    names = sorted({_binding(device_map, ch).device for _, ch, _ in STEPS})
    devices = open_devices(device_map, ctx.api, names)
    try:
        readings = _readings(ctx, device_map, devices)
    finally:
        close_devices(devices)
    calibration = Calibration.model_validate(readings)
    if calibration.collective_bottom_raw == calibration.collective_top_raw:
        raise CliError(
            "device_map.calibration: collective read "
            f"{calibration.collective_top_raw:+.4f} at both ends; was it moved? "
            "profile left unchanged"
        )
    write_calibration(args.profile, calibration)
    ctx.console.line(f"calibration written to {args.profile}")
    return EXIT_OK
