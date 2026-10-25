"""Which force API drives the base: the one place a backend kind is interpreted.

``sdl`` is SDL2's haptic API (every platform); ``dinput8`` drives the base
through DirectInput 8 directly (Windows only), over the same acquired device
object that reads the base's axes.
"""

import sys
from typing import Final, Literal, Protocol, get_args

from wardogs_flight_eng.inputs.dinput_device import DInputJoystick
from wardogs_flight_eng.inputs.sdl_device import SdlDevice
from wardogs_flight_eng.outputs.dinput_haptic import DInputHapticBackend
from wardogs_flight_eng.outputs.haptic_axes import HapticAxisMap
from wardogs_flight_eng.outputs.protocol import ForceBackend
from wardogs_flight_eng.outputs.sdl_haptic import SdlHapticBackend

BackendKind = Literal["sdl", "dinput8"]
BACKEND_KINDS: Final[tuple[BackendKind, ...]] = get_args(BackendKind)

_PLATFORM = sys.platform  # module-level so tests can stand in another host


class HapticBackend(ForceBackend, Protocol):
    """A device force backend: also reports the condition kinds it lacks."""

    @property
    def missing_conditions(self) -> frozenset[str]: ...


def host_platform() -> str:
    """The ``sys.platform`` the backends are chosen for."""
    return _PLATFORM


def platform_supports(kind: BackendKind) -> bool:
    """``sdl`` everywhere; ``dinput8`` only on Windows."""
    return kind == "sdl" or _PLATFORM == "win32"


def build_force_backend(
    kind: BackendKind,
    *,
    sdl_device: SdlDevice | None,
    dinput_joystick: DInputJoystick | None,
    axis_map: HapticAxisMap,
    persistent_length_s: float,
    refresh_every_tick: bool,
) -> HapticBackend:
    """The device backend for ``kind`` over the base opened for it.

    ``sdl`` needs ``sdl_device``; ``dinput8`` needs ``dinput_joystick`` and
    has no ``refresh_every_tick`` mode. A mismatch is a programming error
    (``ValueError``): the CLI refuses those combinations before opening.
    """
    if kind == "sdl":
        if sdl_device is None:
            raise ValueError("the sdl backend needs the base opened through SDL")
        return SdlHapticBackend(
            sdl_device,
            axis_map=axis_map,
            persistent_length_s=persistent_length_s,
            refresh_every_tick=refresh_every_tick,
        )
    if dinput_joystick is None:
        raise ValueError("the dinput8 backend needs the base opened by DirectInput")
    if refresh_every_tick:
        raise ValueError("refresh_every_tick applies to the sdl backend only")
    return DInputHapticBackend(dinput_joystick, persistent_length_s, axis_map=axis_map)
