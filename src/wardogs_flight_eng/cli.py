"""``wardogs-flight-eng``: argument parsing and subcommand dispatch.

Exit codes: 0 ok; 1 usage, profile or configuration error (the message names
the field or channel); 2 a device is missing or was lost. The subcommands
live in ``cli_run``, ``cli_devices``, ``cli_calibrate``, ``cli_offline`` and
``cli_preset``;
output goes through ``cli_console.Console``.
"""

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn, TextIO

from wardogs_flight_eng.cli_calibrate import calibrate_command
from wardogs_flight_eng.cli_console import (
    EXIT_CONFIG,
    EXIT_DEVICE,
    EXIT_OK,
    CliContext,
    CliError,
    Console,
    LineReader,
)
from wardogs_flight_eng.cli_devices import check_device_command, list_devices_command
from wardogs_flight_eng.cli_offline import dry_run_command, show_constants_command
from wardogs_flight_eng.cli_preset import make_preset_command
from wardogs_flight_eng.cli_run import run_command
from wardogs_flight_eng.cockpit_preset import PresetError
from wardogs_flight_eng.constants.loader import ConstantsError
from wardogs_flight_eng.engine.profile import ProfileError
from wardogs_flight_eng.inputs.protocol import DeviceLostError, InputConfigError
from wardogs_flight_eng.inputs.sdl_api import SdlApi, SdlError
from wardogs_flight_eng.runtime.paths import setup_logging

log = logging.getLogger(__name__)

PROG = "wardogs-flight-eng"

Command = Callable[[argparse.Namespace, CliContext], int]

COMMANDS: dict[str, Command] = {
    "run": run_command,
    "dry-run": dry_run_command,
    "list-devices": list_devices_command,
    "check-device": check_device_command,
    "calibrate": calibrate_command,
    "show-constants": show_constants_command,
    "make-preset": make_preset_command,
}

_CONFIG_ERRORS = (ProfileError, ConstantsError, InputConfigError, PresetError, OSError)
_DEVICE_ERRORS = (SdlError, DeviceLostError)


class _Parser(argparse.ArgumentParser):
    """An ``ArgumentParser`` whose usage errors become exit code 1."""

    def error(self, message: str) -> NoReturn:
        raise CliError(f"{message}\n{self.format_usage().rstrip()}", EXIT_CONFIG)


def _positive_rate(text: str) -> float:
    try:
        rate = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not 0 < rate < float("inf"):
        raise argparse.ArgumentTypeError(f"must be a positive rate in Hz: {text}")
    return rate


def _add_run(sub: "argparse._SubParsersAction[_Parser]", common: _Parser) -> None:
    run = sub.add_parser("run", parents=[common], help="drive the force base")
    run.add_argument(
        "--profile",
        type=Path,
        action="append",
        required=True,
        help="profile JSON; repeat to cycle profiles with PROFILE_CYCLE",
    )
    run.add_argument("--rate", type=_positive_rate, default=200.0, help="loop Hz")
    run.add_argument("--log", type=Path, help="also write every command as JSONL")
    run.add_argument(
        "--refresh-every-tick",
        action="store_true",
        help="update and re-run every persistent effect each tick (A/B aid)",
    )


def _add_tools(sub: "argparse._SubParsersAction[_Parser]", common: _Parser) -> None:
    dry = sub.add_parser("dry-run", parents=[common], help="simulate a scenario")
    dry.add_argument("--profile", type=Path, required=True)
    dry.add_argument("--scenario", type=Path, required=True)
    dry.add_argument("--out", type=Path, help="output directory")
    listing = sub.add_parser("list-devices", parents=[common], help="show joysticks")
    listing.add_argument("--live", action="store_true", help="show live values")
    check = sub.add_parser("check-device", parents=[common], help="probe the base")
    check.add_argument("--guid", help="device GUID (default: first with haptics)")
    calibrate = sub.add_parser("calibrate", parents=[common], help="record ranges")
    calibrate.add_argument("--profile", type=Path, required=True)
    sub.add_parser("show-constants", parents=[common], help="print game constants")


def _add_preset(sub: "argparse._SubParsersAction[_Parser]", common: _Parser) -> None:
    preset = sub.add_parser(
        "make-preset", parents=[common], help="write a Moza Cockpit preset"
    )
    preset.add_argument("--profile", type=Path, required=True)
    preset.add_argument(
        "--template", type=Path, required=True, help="your Moza Cockpit export"
    )
    preset.add_argument(
        "--division",
        choices=["A", "B"],
        required=True,
        help="A: Flight Eng owns spring and trim; B: Cockpit does",
    )
    preset.add_argument("--out", type=Path, required=True, help="new .preset file")
    preset.add_argument(
        "--name", help="preset name (default: template name + division)"
    )


def build_parser() -> _Parser:
    common = _Parser(add_help=False)
    common.add_argument("--verbose", action="store_true", help="debug logging")
    parser = _Parser(prog=PROG, description="Wardogs helicopter force feedback")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    _add_run(sub, common)
    _add_tools(sub, common)
    _add_preset(sub, common)
    return parser


def _dispatch(args: argparse.Namespace, ctx: CliContext) -> int:
    """Run the subcommand; map every expected failure to its exit code."""
    try:
        return COMMANDS[args.command](args, ctx)
    except CliError as err:
        failure, code = str(err), err.code
    except _CONFIG_ERRORS as err:
        failure, code = str(err), EXIT_CONFIG
    except _DEVICE_ERRORS as err:
        failure, code = str(err), EXIT_DEVICE
    except KeyboardInterrupt:
        failure, code = "interrupted before completion", EXIT_CONFIG
    log.debug("%s failed with exit code %d: %s", args.command, code, failure)
    ctx.console.error(failure)
    return code


def main(
    argv: Sequence[str] | None = None,
    *,
    console: TextIO | None = None,
    api: SdlApi | None = None,
    stdin: LineReader | None = None,
) -> int:
    """Parse ``argv`` (default ``sys.argv[1:]``), run it, return the exit code.

    ``console`` is the stream user output goes to (default stdout), ``api``
    the SDL implementation (default the real one) and ``stdin`` where
    ``calibrate`` reads Enter presses (default ``sys.stdin``).
    """
    out = Console(console)
    try:
        args = build_parser().parse_args(argv)
    except CliError as err:
        out.error(str(err))
        return err.code
    except SystemExit as done:  # --help printed its text
        return done.code if isinstance(done.code, int) else EXIT_OK
    setup_logging(args.verbose)
    ctx = CliContext(out, api, sys.stdin if stdin is None else stdin)
    return _dispatch(args, ctx)
