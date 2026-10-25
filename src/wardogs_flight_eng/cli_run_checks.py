"""What ``run`` checks before it drives the base.

``check_backend_options`` reads the arguments alone, ``shared_map`` and
``haptic_axes`` the profiles alone, all before any device is opened.
``check_force_base`` runs once the base is open. ``refuse_unboosted_without_friction``
is pure as well, but runs after the base opens: the caller supplies the
condition kinds the base lacks, read from the one force channel it opens.
"""

from collections.abc import Sequence
from pathlib import Path

from wardogs_flight_eng.cli_console import EXIT_CONFIG, CliError
from wardogs_flight_eng.cli_dinput_devices import require_backend
from wardogs_flight_eng.engine.device_map import DeviceMap
from wardogs_flight_eng.engine.profile import Profile
from wardogs_flight_eng.inputs.dinput_device import DInputJoystick, ff_actuator_check
from wardogs_flight_eng.inputs.protocol import InputConfigError, InputDevice
from wardogs_flight_eng.inputs.sdl_device import SdlDevice
from wardogs_flight_eng.outputs.backend_choice import BackendKind
from wardogs_flight_eng.outputs.haptic_axes import HapticAxisMap


def check_backend_options(kind: BackendKind, refresh_every_tick: bool) -> None:
    """``--refresh-every-tick`` is an SDL mode; ``dinput8`` needs Windows."""
    if refresh_every_tick and kind != "sdl":
        raise CliError("--refresh-every-tick applies to the sdl backend only")
    require_backend(kind)


def _first_difference(a: object, b: object, where: str) -> str | None:
    """Dotted path of the first value that differs between two JSON trees."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in [*a, *(k for k in b if k not in a)]:
            if key not in a or key not in b:
                return f"{where}.{key}"
            found = _first_difference(a[key], b[key], f"{where}.{key}")
            if found is not None:
                return found
        return None
    return None if a == b else where


def shared_map(paths: Sequence[Path], profiles: Sequence[Profile]) -> DeviceMap:
    """The one device map every profile shares; it must bind something."""
    first = profiles[0].device_map
    for path, profile in zip(paths[1:], profiles[1:], strict=True):
        differs = _first_difference(
            first.model_dump(mode="json"),
            profile.device_map.model_dump(mode="json"),
            "device_map",
        )
        if differs is not None:
            raise CliError(
                f"profile {path}: {differs} differs from {paths[0]}; every "
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


def haptic_axes(device_map: DeviceMap) -> tuple[str, HapticAxisMap]:
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


def refuse_unboosted_without_friction(
    profiles: Sequence[Profile], missing: frozenset[str], device_name: str
) -> None:
    """An unboosted profile needs friction to hold its trim clamp."""
    if "friction" not in missing:
        return
    for profile in profiles:
        if profile.feel.mode == "unboosted":
            raise CliError(
                f"profile {profile.name!r} uses feel.mode 'unboosted' but the "
                f"base {device_name!r} reports no friction primitive, so the "
                "trim clamp could not hold; set feel.mode to 'force_trim' in "
                "that profile or use a base with friction",
                EXIT_CONFIG,
            )


def check_force_base(device: InputDevice, alias: str, axis_map: HapticAxisMap) -> None:
    """SDL: the joystick reports haptics; DirectInput: pitch and roll are
    force-feedback actuator axes."""
    if isinstance(device, DInputJoystick):
        try:
            ff_actuator_check(device, axis_map)
        except InputConfigError as err:
            raise CliError(f"device_map.axes.pitch/roll: {err}") from err
        return
    if not isinstance(device, SdlDevice):
        return
    if device.api.SDL_JoystickIsHaptic(device.joystick) != 1:
        raise CliError(
            f"device_map.axes.pitch/roll: device {alias!r} "
            f"({device.name}) has no force feedback"
        )
