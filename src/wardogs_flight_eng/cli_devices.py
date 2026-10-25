"""Device subcommands (``list-devices``, ``check-device``) over SDL.

The ``--backend dinput8`` variants live in ``cli_dinput_devices``; opening the
mapped devices for ``run``, ``calibrate`` and ``record`` in ``cli_device_open``.
"""

import argparse
import logging
from dataclasses import fields
from time import sleep

from wardogs_flight_eng.cli_console import (
    EXIT_CONFIG,
    EXIT_DEVICE,
    EXIT_OK,
    CliContext,
    CliError,
    Console,
)
from wardogs_flight_eng.inputs.sdl_api import SdlApi
from wardogs_flight_eng.inputs.sdl_device import (
    DeviceInfo,
    SdlDevice,
    enumerate_devices,
)
from wardogs_flight_eng.inputs.sdl_real import default_api
from wardogs_flight_eng.outputs.sdl_probe import PrimitiveReport, probe_primitives

log = logging.getLogger(__name__)

LIVE_PERIOD_S = 0.1
CONDITION_PRIMITIVES = frozenset({"friction", "damper", "inertia"})
CONDITION_WARNING = (
    "unboosted profiles cannot run without friction; "
    "force_trim profiles run without the missing conditions"
)


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
    """Probe every primitive; exit 1 if a required one was refused.

    Required: spring, spring_center_moves, sine, constant. Friction, damper and
    inertia are optional: missing ones print a WARN and still exit 0, since
    force-trim profiles run without them.
    """
    target = _probe_target(enumerate_devices(ctx.api), args.guid)
    report = probe_primitives(target.guid, ctx.api)
    ctx.console.line(f"device: {target.name} ({target.guid})")
    return report_primitives(ctx.console, report)


def report_primitives(console: Console, report: PrimitiveReport) -> int:
    """Print the primitive table and verdict; the exit code it implies."""
    results = [(f.name, bool(getattr(report, f.name))) for f in fields(report)]
    console.table(
        ("primitive", "accepted"), ((n, "yes" if ok else "no") for n, ok in results)
    )
    missing = [name for name, ok in results if not ok]
    required = [name for name in missing if name not in CONDITION_PRIMITIVES]
    if required:
        console.line(f"FAIL: not accepted: {', '.join(missing)}")
        return EXIT_CONFIG
    if missing:
        console.line(f"WARN: not accepted: {', '.join(missing)} ({CONDITION_WARNING})")
        return EXIT_OK
    console.line("PASS: every force primitive was accepted")
    return EXIT_OK
