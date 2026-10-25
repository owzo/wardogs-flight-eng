"""``--backend dinput8``: the DirectInput adapter and its device subcommands.

``list-devices`` and ``check-device`` pick their variant by ``--backend`` here.
Each command that resolves the DirectInput object closes it when it ends
(``dinput_session``); the adapter's ``close`` is idempotent, since a force
backend built over it closes it as well.
"""

import argparse
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import sleep

from wardogs_flight_eng.cli_console import EXIT_DEVICE, EXIT_OK, CliContext, CliError
from wardogs_flight_eng.cli_devices import (
    LIVE_PERIOD_S,
    check_device_command,
    list_devices_command,
    report_primitives,
)
from wardogs_flight_eng.inputs.dinput_api import (
    DIJOFS_BY_INDEX,
    DiAxisInfo,
    DiDeviceInfo,
    DirectInputApi,
)
from wardogs_flight_eng.inputs.dinput_device import DInputJoystick, open_dinput_instance
from wardogs_flight_eng.outputs.backend_choice import (
    BACKEND_KINDS,
    BackendKind,
    host_platform,
    platform_supports,
)
from wardogs_flight_eng.outputs.dinput_probe import probe_dinput

log = logging.getLogger(__name__)

_DIJOFS_NAMES = ("X", "Y", "Z", "RX", "RY", "RZ", "SLIDER(0)", "SLIDER(1)")


def real_dinput_api() -> DirectInputApi:
    """The ctypes DirectInput 8 adapter (``inputs.dinput_real``)."""
    raise CliError("the DirectInput adapter is not available in this build")


def require_backend(kind: BackendKind) -> None:
    """Refuse a backend this host cannot drive, before any device opens."""
    if not platform_supports(kind):
        raise CliError(f"--backend {kind} is not available on {host_platform()}")


@contextmanager
def directinput(ctx: CliContext) -> Iterator[DirectInputApi]:
    """The DirectInput object (``ctx.dinput_api``, else the real adapter),
    closed when the block ends; refused off Windows before it is resolved."""
    require_backend("dinput8")
    api = real_dinput_api() if ctx.dinput_api is None else ctx.dinput_api
    try:
        yield api
    finally:
        api.close()


@contextmanager
def dinput_session(
    ctx: CliContext, kind: BackendKind
) -> Iterator[DirectInputApi | None]:
    """``directinput`` under ``dinput8``; None under ``sdl``."""
    if kind == "sdl":
        yield None
        return
    with directinput(ctx) as api:
        yield api


def add_backend_argument(parser: argparse.ArgumentParser) -> None:
    """``--backend``, on ``run``, ``check-device`` and ``list-devices``."""
    parser.add_argument(
        "--backend",
        choices=BACKEND_KINDS,
        default="sdl",
        help="force API: sdl, or dinput8 (Windows only)",
    )


def list_devices_by_backend(args: argparse.Namespace, ctx: CliContext) -> int:
    if args.backend == "dinput8":
        return list_dinput_devices_command(args, ctx)
    return list_devices_command(args, ctx)


def check_device_by_backend(args: argparse.Namespace, ctx: CliContext) -> int:
    if args.backend == "dinput8":
        return check_dinput_device_command(args, ctx)
    return check_device_command(args, ctx)


def _offset(axis: DiAxisInfo) -> str:
    if axis.offset not in DIJOFS_BY_INDEX:
        return str(axis.offset)
    return f"{axis.offset} DIJOFS_{_DIJOFS_NAMES[DIJOFS_BY_INDEX.index(axis.offset)]}"


def _axis_cells(index: int, axis: DiAxisInfo) -> tuple[str, str, str, str]:
    actuator = "yes" if axis.ff_actuator else "no"
    return str(index), _offset(axis), axis.name, actuator


def check_dinput_device_command(args: argparse.Namespace, ctx: CliContext) -> int:
    """Probe the base matching ``--guid`` through DirectInput; same verdict as SDL."""
    if args.guid is None:
        raise CliError(
            "check-device --backend dinput8 needs --guid: DirectInput matching "
            "reads the vid:pid from the SDL GUID (see `list-devices`)"
        )
    with directinput(ctx) as api:
        report, detail = probe_dinput(api, args.guid)
    state = "acquired" if detail.acquired else "not acquired"
    ctx.console.line(f"device: {detail.instance_name} ({state}, gain {detail.ff_gain})")
    ctx.console.table(
        ("index", "offset", "name", "actuator"),
        (_axis_cells(i, axis) for i, axis in enumerate(detail.axes)),
    )
    return report_primitives(ctx.console, report)


def list_dinput_devices_command(args: argparse.Namespace, ctx: CliContext) -> int:
    with directinput(ctx) as api:
        infos = api.enumerate_devices()
        if not infos:
            ctx.console.line("no DirectInput game controllers attached")
            return EXIT_OK
        ctx.console.table(
            ("instance", "product", "vid:pid", "force feedback"),
            (
                (i.instance_name, i.product_name, f"{i.vid:04x}:{i.pid:04x}")
                + ("yes" if i.force_feedback else "no",)
                for i in infos
            ),
        )
        if args.live:
            _live(api, infos, ctx)
    return EXIT_OK


def _live(api: DirectInputApi, infos: list[DiDeviceInfo], ctx: CliContext) -> None:
    """Reprint the first force-feedback instance's axes until Ctrl+C."""
    found = [info for info in infos if info.force_feedback]
    if not found:
        raise CliError("no force-feedback DirectInput device is attached", EXIT_DEVICE)
    joystick = open_dinput_instance(api, found[0], found[0].instance_guid)
    try:
        if joystick.unreadable_axes:
            names = ", ".join(axis.name for axis in joystick.unreadable_axes)
            ctx.console.line(f"unreadable: {names}")
        ctx.console.line(f"live values every {LIVE_PERIOD_S} s; Ctrl+C to stop")
        while True:
            _live_lines(joystick, ctx)
            sleep(LIVE_PERIOD_S)
    except KeyboardInterrupt:
        log.debug("live DirectInput view stopped by Ctrl+C")
    finally:
        joystick.close()


def _live_lines(joystick: DInputJoystick, ctx: CliContext) -> None:
    joystick.poll()
    ctx.console.line()
    for index, axis in enumerate(joystick.axes_info):
        cells = " ".join(_axis_cells(index, axis))
        ctx.console.line(f"{cells} {joystick.axis(index):+.2f}")
