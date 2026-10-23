"""``run``: drive the force-feedback base from the bound devices until stopped.

Everything that can be checked from the profiles alone is checked before any
device is opened. Opened joysticks are always closed again; the force backend
is zeroed and released by ``run_loop``'s teardown (or here, if the loop never
starts).
"""

import argparse
import logging
import signal
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import FrameType
from typing import Final

from wardogs_flight_eng.cli_console import (
    EXIT_CONFIG,
    EXIT_DEVICE,
    EXIT_OK,
    CliContext,
    CliError,
)
from wardogs_flight_eng.cli_devices import close_devices, open_devices
from wardogs_flight_eng.cli_profiles import load_checked_profile
from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.device_map import DeviceMap
from wardogs_flight_eng.engine.profile import Profile
from wardogs_flight_eng.engine.synth import FlightEngine
from wardogs_flight_eng.inputs.composite import CompositeInput
from wardogs_flight_eng.inputs.sdl_device import SdlDevice
from wardogs_flight_eng.outputs.clamp import ClampedBackend
from wardogs_flight_eng.outputs.haptic_axes import HapticAxisMap
from wardogs_flight_eng.outputs.logging_backend import LoggingBackend
from wardogs_flight_eng.outputs.protocol import ForceBackend
from wardogs_flight_eng.outputs.sdl_haptic import SdlHapticBackend
from wardogs_flight_eng.outputs.tee import TeeBackend
from wardogs_flight_eng.runtime.loop import LoopResult, StopReason, run_loop

log = logging.getLogger(__name__)

MIN_PERSISTENT_LENGTH_S: Final = 1.0
EXIT_BY_REASON: Final[dict[StopReason, int]] = {
    "stop": EXIT_OK,
    "max_ticks": EXIT_OK,
    "device_lost": EXIT_DEVICE,
    "error": EXIT_CONFIG,
}


def _shared_map(paths: Sequence[Path], profiles: Sequence[Profile]) -> DeviceMap:
    """The one device map every profile shares; it must bind something."""
    first = profiles[0].device_map
    for path, profile in zip(paths[1:], profiles[1:], strict=True):
        if profile.device_map != first:
            raise CliError(
                f"profile {path}: device_map differs from {paths[0]}; every "
                "profile in one run must share one device_map"
            )
    if not first.devices or not first.axes:
        raise CliError(
            f"profile {paths[0]}: device_map binds no devices or axes. Run "
            "`wardogs-flight-eng list-devices --live` to identify your devices, "
            "fill device_map in the profile, then run "
            f"`wardogs-flight-eng calibrate --profile {paths[0]}`"
        )
    return first


def _haptic_axes(device_map: DeviceMap) -> tuple[str, HapticAxisMap]:
    """The force-feedback device's name and its pitch/roll haptic axes."""
    for channel in ("pitch", "roll"):
        if channel not in device_map.axes:
            raise CliError(
                f"device_map.axes.{channel}: not bound; the force-feedback "
                "base must supply pitch and roll"
            )
    pitch, roll = device_map.axes["pitch"], device_map.axes["roll"]
    if roll.device != pitch.device:
        raise CliError(
            f"device_map.axes.roll: bound to {roll.device!r} but pitch is on "
            f"{pitch.device!r}; both must be axes of the force-feedback base"
        )
    try:
        return pitch.device, HapticAxisMap.from_bindings(pitch=pitch, roll=roll)
    except ValueError as err:
        raise CliError(f"device_map.axes.pitch/roll: {err}") from err


def _force_backend(
    args: argparse.Namespace,
    device: SdlDevice,
    axis_map: HapticAxisMap,
    profiles: Sequence[Profile],
) -> ForceBackend:
    """Clamp -> [tee ->] SDL haptic, with the strictest ceiling of the profiles."""
    watchdog_s = profiles[0].safety.watchdog_s
    output: ForceBackend = SdlHapticBackend(
        device,
        axis_map=axis_map,
        persistent_length_s=max(MIN_PERSISTENT_LENGTH_S, 2 * watchdog_s),
    )
    if args.log is not None:
        try:
            output = TeeBackend(output, LoggingBackend(args.log))
        except OSError as err:
            output.close()
            raise CliError(f"--log {args.log}: {err.strerror or err}") from err
    ceiling = min(profile.safety.force_ceiling for profile in profiles)
    return ClampedBackend(output, ceiling=ceiling)


@contextmanager
def _ctrl_c_requests_stop() -> Iterator[threading.Event]:
    """First Ctrl+C asks the loop to stop after its tick; a second interrupts."""
    requested = threading.Event()

    def on_ctrl_c(_signum: int, _frame: FrameType | None) -> None:
        requested.set()
        signal.signal(signal.SIGINT, signal.default_int_handler)
        log.info("Ctrl+C: stopping after this tick (press again to interrupt)")

    if threading.current_thread() is not threading.main_thread():
        yield requested  # signals reach only the main thread
        return
    previous = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, on_ctrl_c)
    try:
        yield requested
    finally:
        restored = signal.default_int_handler if previous is None else previous
        signal.signal(signal.SIGINT, restored)


def _fly(
    args: argparse.Namespace,
    engines: Sequence[FlightEngine],
    source: CompositeInput,
    backend: ForceBackend,
    watchdog_s: float,
) -> LoopResult | None:
    """Run the loop; ``None`` if it was interrupted (teardown still ran)."""
    with _ctrl_c_requests_stop() as stop:
        try:
            return run_loop(
                engines,
                source,
                backend,
                rate_hz=args.rate,
                watchdog_s=watchdog_s,
                stop=stop.is_set,
            )
        except KeyboardInterrupt:
            log.info("loop interrupted; forces zeroed and device released")
            return None


def run_command(args: argparse.Namespace, ctx: CliContext) -> int:
    paths: list[Path] = args.profile
    constants = load_constants()
    profiles = [load_checked_profile(path, constants) for path in paths]
    device_map = _shared_map(paths, profiles)
    base, axis_map = _haptic_axes(device_map)
    engines = [FlightEngine(profile, constants) for profile in profiles]
    devices = open_devices(device_map, ctx.api)
    try:
        if devices[base].api.SDL_JoystickIsHaptic(devices[base].joystick) != 1:
            raise CliError(
                f"device_map.axes.pitch/roll: device {base!r} "
                f"({devices[base].name}) has no force feedback"
            )
        source = CompositeInput(device_map, devices)
        backend = _force_backend(args, devices[base], axis_map, profiles)
        names = ", ".join(profile.name for profile in profiles)
        ctx.console.line(f"running {names} at {args.rate:g} Hz; Ctrl+C to stop")
        result = _fly(args, engines, source, backend, profiles[0].safety.watchdog_s)
    finally:
        close_devices(devices)
    if result is None:
        ctx.console.line("stopped: interrupted; forces off, devices released")
        return EXIT_OK
    ctx.console.line(
        f"stopped: {result.stopped_by} after {result.ticks} ticks "
        f"(active profile {result.active_profile})"
    )
    return EXIT_BY_REASON[result.stopped_by]
