"""``run``: drive the force-feedback base from the bound devices until stopped.

Everything that can be checked from the profiles alone is checked before any
device is opened (``cli_run_checks``). Opened joysticks are always closed
again. The force backend is zeroed and released by ``run_loop``'s teardown,
or here if the loop never took it over; the final message claims a release
only if ``close`` actually completed (``cli_interrupt.ReleaseWatch``).
"""

import argparse
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from wardogs_flight_eng.cli_console import (
    EXIT_DEVICE,
    EXIT_OK,
    CliContext,
    CliError,
)
from wardogs_flight_eng.cli_devices import close_devices, open_devices
from wardogs_flight_eng.cli_interrupt import ReleaseWatch, ctrl_c_requests_stop
from wardogs_flight_eng.cli_profiles import load_checked_profile
from wardogs_flight_eng.cli_run_checks import (
    haptic_axes,
    refuse_unboosted_without_friction,
    shared_map,
)
from wardogs_flight_eng.constants.loader import load_constants
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
    "error": EXIT_DEVICE,  # a failing tick is a runtime fault, not configuration
}
UNCONFIRMED: Final = (
    "the force base did not confirm its release; power-cycle it if it still pushes"
)


@dataclass(frozen=True, slots=True)
class _Outcome:
    result: LoopResult | None  # None: interrupted
    released: bool


def _force_backend(
    args: argparse.Namespace,
    device: SdlDevice,
    axis_map: HapticAxisMap,
    profiles: Sequence[Profile],
    watchdog_s: float,
) -> ReleaseWatch:
    """Clamp -> [tee ->] SDL haptic, with the strictest ceiling of the profiles.

    An unboosted profile on a base without friction is refused here, on the
    one haptic channel, before any force is commanded; the channel is closed.
    """
    haptic = SdlHapticBackend(
        device,
        axis_map=axis_map,
        persistent_length_s=max(MIN_PERSISTENT_LENGTH_S, 2 * watchdog_s),
        refresh_every_tick=args.refresh_every_tick,
    )
    try:
        refuse_unboosted_without_friction(
            profiles, haptic.missing_conditions, device.name
        )
    except CliError:
        haptic.close()
        raise
    output: ForceBackend = haptic
    if args.log is not None:
        try:
            output = TeeBackend(output, LoggingBackend(args.log))
        except OSError as err:
            output.close()
            raise CliError(f"--log {args.log}: {err.strerror or err}") from err
    ceiling = min(profile.safety.force_ceiling for profile in profiles)
    return ReleaseWatch(ClampedBackend(output, ceiling=ceiling))


def _close_unowned(backend: ReleaseWatch) -> None:
    """Release a backend the loop never took over (it failed before starting)."""
    try:
        backend.close()
    except Exception:
        log.exception("closing the force backend failed")


def _fly(
    args: argparse.Namespace,
    engines: Sequence[FlightEngine],
    source: CompositeInput,
    build: Callable[[], ReleaseWatch],
    watchdog_s: float,
) -> _Outcome:
    """Build the backend and run the loop; the backend is closed on every path.

    The Ctrl+C handler is installed before the backend is built, so a press
    while the haptic opens only requests the stop: the loop then runs zero
    ticks and its teardown releases the base instead of leaking it.
    """
    backend: ReleaseWatch | None = None
    result: LoopResult | None = None
    try:
        with ctrl_c_requests_stop() as stop:
            backend = build()
            result = run_loop(
                engines,
                source,
                backend,
                rate_hz=args.rate,
                watchdog_s=watchdog_s,
                stop=stop.is_set,
            )
    except KeyboardInterrupt:
        log.warning("run interrupted")
    finally:
        if backend is not None and not backend.close_attempted:
            _close_unowned(backend)
    return _Outcome(result, backend is not None and backend.released)


def _report(ctx: CliContext, outcome: _Outcome) -> int:
    result = outcome.result
    if result is None:
        if outcome.released:
            ctx.console.line("stopped: interrupted; forces off, base released")
            return EXIT_OK
        ctx.console.line(f"stopped: interrupted; {UNCONFIRMED}")
        return EXIT_DEVICE
    ctx.console.line(
        f"stopped: {result.stopped_by} after {result.ticks} ticks "
        f"(active profile {result.active_profile})"
    )
    if not outcome.released:
        ctx.console.line(f"warning: {UNCONFIRMED}")
        return EXIT_DEVICE
    return EXIT_BY_REASON[result.stopped_by]


def run_command(args: argparse.Namespace, ctx: CliContext) -> int:
    paths: list[Path] = args.profile
    constants = load_constants()
    profiles = [load_checked_profile(path, constants) for path in paths]
    device_map = shared_map(paths, profiles)
    base, axis_map = haptic_axes(device_map)
    watchdog_s = min(profile.safety.watchdog_s for profile in profiles)
    engines = [FlightEngine(profile, constants) for profile in profiles]
    devices = open_devices(device_map, ctx.api)
    try:
        if devices[base].api.SDL_JoystickIsHaptic(devices[base].joystick) != 1:
            raise CliError(
                f"device_map.axes.pitch/roll: device {base!r} "
                f"({devices[base].name}) has no force feedback"
            )
        source = CompositeInput(device_map, devices)
        names = ", ".join(profile.name for profile in profiles)
        ctx.console.line(f"running {names} at {args.rate:g} Hz; Ctrl+C to stop")
        outcome = _fly(
            args,
            engines,
            source,
            lambda: _force_backend(args, devices[base], axis_map, profiles, watchdog_s),
            watchdog_s,
        )
    finally:
        close_devices(devices)
    return _report(ctx, outcome)
