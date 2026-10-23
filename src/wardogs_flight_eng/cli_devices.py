"""Device subcommands (``list-devices``, ``check-device``) and device opening."""

import argparse
import logging
from collections.abc import Iterable
from dataclasses import fields
from time import sleep

from wardogs_flight_eng.cli_console import (
    EXIT_CONFIG,
    EXIT_DEVICE,
    EXIT_OK,
    CliContext,
    CliError,
)
from wardogs_flight_eng.engine.device_map import DeviceMap, DeviceRef
from wardogs_flight_eng.inputs.protocol import InputConfigError
from wardogs_flight_eng.inputs.sdl_api import SdlApi
from wardogs_flight_eng.inputs.sdl_device import (
    DeviceInfo,
    SdlDevice,
    enumerate_devices,
    open_by_guid,
)
from wardogs_flight_eng.inputs.sdl_real import default_api
from wardogs_flight_eng.outputs.sdl_probe import probe_primitives

log = logging.getLogger(__name__)

LIVE_PERIOD_S = 0.1


def _open_one(name: str, ref: DeviceRef, api: SdlApi | None) -> SdlDevice:
    """Open by GUID; without one, the first device whose name holds ``product``."""
    if ref.guid is not None:
        try:
            return open_by_guid(ref.guid, api)
        except InputConfigError as err:
            raise CliError(
                f"device {name!r} (guid {ref.guid}) is not attached", EXIT_DEVICE
            ) from err
    if ref.product is None:
        raise CliError(f"device_map.devices.{name}: needs a guid or a product")
    wanted = ref.product.lower()
    found = [d for d in enumerate_devices(api) if wanted in d.name.lower()]
    if not found:
        raise CliError(
            f"device {name!r} (product {ref.product!r}) is not attached", EXIT_DEVICE
        )
    return open_by_guid(found[0].guid, api)


def open_devices(
    device_map: DeviceMap, api: SdlApi | None, names: Iterable[str] | None = None
) -> dict[str, SdlDevice]:
    """Open ``names`` (default: every mapped device); all or none stay open."""
    opened: dict[str, SdlDevice] = {}
    try:
        for name in device_map.devices if names is None else names:
            opened[name] = _open_one(name, device_map.devices[name], api)
            log.info("opened %r: %s (%s)", name, opened[name].name, opened[name].guid)
    except BaseException:
        close_devices(opened)
        raise
    return opened


def close_devices(devices: dict[str, SdlDevice]) -> None:
    for device in devices.values():
        device.close()


def list_devices_command(args: argparse.Namespace, ctx: CliContext) -> int:
    infos = enumerate_devices(ctx.api)
    if not infos:
        ctx.console.line("no joysticks attached")
        return EXIT_OK
    ctx.console.table(
        ("index", "guid", "name", "axes", "buttons", "haptic"),
        (
            (str(i.index), i.guid, i.name, str(i.axis_count), str(i.button_count))
            + ("yes" if i.has_haptic else "no",)
            for i in infos
        ),
    )
    if args.live:
        _live(infos, default_api() if ctx.api is None else ctx.api, ctx)
    return EXIT_OK


def _live(infos: list[DeviceInfo], api: SdlApi, ctx: CliContext) -> None:
    """Reprint every device's axes and held buttons until Ctrl+C."""
    devices: list[tuple[int, SdlDevice]] = []
    try:
        for info in infos:
            joystick = api.SDL_JoystickOpen(info.index)
            if joystick is None:
                log.warning(
                    "cannot open joystick %d: %s", info.index, api.SDL_GetError()
                )
                continue
            devices.append((info.index, SdlDevice(api, joystick, info)))
        ctx.console.line(f"live values every {LIVE_PERIOD_S} s; Ctrl+C to stop")
        while True:
            ctx.console.line()
            for index, device in devices:
                device.poll()
                ctx.console.line(_live_line(index, device))
            sleep(LIVE_PERIOD_S)
    except KeyboardInterrupt:
        log.debug("live device view stopped by Ctrl+C")
    finally:
        for _, device in devices:
            device.close()


def _live_line(index: int, device: SdlDevice) -> str:
    if not device.alive:
        return f"[{index}] {device.name}: disconnected"
    axes = " ".join(f"{device.axis(a):+.2f}" for a in range(device.axis_count))
    held = [str(b) for b in range(device.button_count) if device.button(b)]
    return f"[{index}] {device.name}: axes {axes}  held: {', '.join(held) or 'none'}"


def _probe_target(infos: list[DeviceInfo], guid: str | None) -> DeviceInfo:
    if guid is None:
        haptic = [info for info in infos if info.has_haptic]
        if not haptic:
            raise CliError("no force-feedback device is attached", EXIT_DEVICE)
        return haptic[0]
    found = [info for info in infos if info.guid.lower() == guid.lower()]
    if not found:
        raise CliError(f"no device with guid {guid} is attached", EXIT_DEVICE)
    if not found[0].has_haptic:
        raise CliError(f"device {found[0].name!r} has no force feedback", EXIT_CONFIG)
    return found[0]


def check_device_command(args: argparse.Namespace, ctx: CliContext) -> int:
    """Probe the four primitives; exit 0 only if every one was accepted."""
    target = _probe_target(enumerate_devices(ctx.api), args.guid)
    report = probe_primitives(target.guid, ctx.api)
    results = [(f.name, bool(getattr(report, f.name))) for f in fields(report)]
    ctx.console.line(f"device: {target.name} ({target.guid})")
    ctx.console.table(
        ("primitive", "accepted"), ((n, "yes" if ok else "no") for n, ok in results)
    )
    if all(ok for _, ok in results):
        ctx.console.line("PASS: every force primitive was accepted")
        return EXIT_OK
    missing = ", ".join(name for name, ok in results if not ok)
    ctx.console.line(f"FAIL: not accepted: {missing}")
    return EXIT_CONFIG
