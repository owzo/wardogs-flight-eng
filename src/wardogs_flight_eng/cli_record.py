"""``record``: capture the real controls into a scenario ``dry-run`` replays.

Reads the profile's devices raw (no ``CompositeInput``, so no calibration or
full binding is needed) and never constructs a force backend: no haptic
device is opened and no force is commanded.
"""

import argparse
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wardogs_flight_eng.cli_console import EXIT_OK, CliContext, CliError
from wardogs_flight_eng.cli_devices import close_devices, open_devices
from wardogs_flight_eng.cli_interrupt import ctrl_c_requests_stop
from wardogs_flight_eng.cli_profiles import load_checked_profile
from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.device_map import Calibration, DeviceMap
from wardogs_flight_eng.inputs.protocol import DeviceLostError
from wardogs_flight_eng.inputs.sdl_api import SdlError
from wardogs_flight_eng.inputs.sdl_device import SdlDevice
from wardogs_flight_eng.runtime.recorder import DeviceSnapshot, ScenarioRecorder

log = logging.getLogger(__name__)


@dataclass(slots=True)
class _Session:
    """The recording in progress: settings, the recorder and ticks done."""

    recorder: ScenarioRecorder
    rate_hz: float
    max_ticks: int | None
    ticks: int = 0

    @property
    def seconds(self) -> float:
        return self.ticks / self.rate_hz

    def finish(self, device_map: DeviceMap) -> dict[str, Any]:
        return self.recorder.finish(self.ticks / self.rate_hz, device_map)


def min_change_arg(text: str) -> float:
    """``--min-change``: a finite number of raw axis units, 0 or more."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not 0 <= value < float("inf"):
        raise argparse.ArgumentTypeError(
            f"--min-change must be a finite number >= 0: {text}"
        )
    return value


def _snapshot(devices: dict[str, SdlDevice]) -> dict[str, DeviceSnapshot]:
    """Poll every device and read its raw axes and buttons."""
    snapshot: dict[str, DeviceSnapshot] = {}
    for alias, device in devices.items():
        device.poll()
        if not device.alive:
            raise DeviceLostError(f"device {alias!r} ({device.name}) was lost")
        snapshot[alias] = DeviceSnapshot(
            tuple(device.axis(i) for i in range(device.axis_count)),
            tuple(device.button(i) for i in range(device.button_count)),
        )
    return snapshot


def _capture(
    session: _Session, devices: dict[str, SdlDevice], stop: threading.Event
) -> None:
    """Record at ``rate_hz`` slots until Ctrl+C or ``max_ticks``."""
    period = 1.0 / session.rate_hz
    session.recorder.begin(0.0, _snapshot(devices))
    deadline = time.perf_counter()
    while not stop.is_set() and session.ticks != session.max_ticks:
        deadline += period
        now = time.perf_counter()
        if deadline < now:  # overrun: restart the schedule from now
            deadline = now
        time.sleep(max(0.0, deadline - now))
        tick = session.ticks + 1
        session.recorder.observe(tick / session.rate_hz, _snapshot(devices))
        session.ticks = tick


def _write(path: Path, document: dict[str, Any]) -> None:
    """Write via a staging file and ``os.replace``: never a truncated file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(document, indent=2, allow_nan=False) + "\n"
    staging = path.with_name(f"{path.name}.tmp")
    try:
        staging.write_text(text, encoding="utf-8", newline="\n")
        os.replace(staging, path)
    except OSError:
        staging.unlink(missing_ok=True)
        raise
    log.info("scenario written to %s", path)


def _checked_settings(args: argparse.Namespace) -> int | None:
    """``--duration`` as a tick count (``None`` = until Ctrl+C)."""
    duration: float | None = args.duration
    if duration is None:
        return None
    if not 0 < duration < float("inf"):
        raise CliError(f"--duration must be a positive number of seconds: {duration}")
    rate: float = args.rate
    return max(1, round(duration * rate))


def _device_map(args: argparse.Namespace) -> DeviceMap:
    device_map = load_checked_profile(args.profile, load_constants()).device_map
    if not device_map.devices:
        raise CliError(
            f"{args.profile}: device_map names no devices; "
            "fill it from list-devices before recording"
        )
    if device_map.calibration == Calibration():
        log.warning(
            "the profile's calibration is the shipped default; "
            "a replay of this recording will use the default calibration"
        )
    return device_map


def record_command(args: argparse.Namespace, ctx: CliContext) -> int:
    """Record to ``--out``; on device loss write the partial file and re-raise."""
    out: Path = args.out
    if out.resolve() == args.profile.resolve():
        raise CliError(f"--out {out}: refuses to overwrite the profile it reads")
    max_ticks = _checked_settings(args)
    device_map = _device_map(args)
    session = _Session(
        ScenarioRecorder(args.rate, args.min_change), args.rate, max_ticks
    )
    devices = open_devices(device_map, ctx.api)
    try:
        with ctrl_c_requests_stop() as stop:
            _capture(session, devices, stop)
    except (DeviceLostError, SdlError, KeyboardInterrupt):
        if session.recorder.step_count:
            _write(out, session.finish(device_map))
            ctx.console.line(f"partial recording ({session.seconds:.2f} s) -> {out}")
        raise
    finally:
        close_devices(devices)
    _write(out, session.finish(device_map))
    ctx.console.line(
        f"recorded {session.ticks} ticks ({session.seconds:.2f} s), "
        f"{session.recorder.step_count} steps -> {out}"
    )
    return EXIT_OK
