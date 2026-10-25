"""The force base as an ``InputDevice`` over one acquired DirectInput device.

SDL opens every DirectInput joystick exclusively, so under ``--backend
dinput8`` the base is read and driven through this single device object.
``open_dinput_joystick`` matches the SDL GUID, then sets exclusive background
cooperation, auto-centre off and full gain, acquires, resets and switches the
actuators on. Axis ``i`` is the ``i``-th axis object in ``dwOfs`` order, the
order SDL's DirectInput driver numbers them.
"""

import logging

from wardogs_flight_eng.inputs.dinput_api import (
    DIERR_INPUTLOST,
    DIERR_NOTACQUIRED,
    DIERR_UNPLUGGED,
    DIJOFS_BY_INDEX,
    DiAxisInfo,
    DiDeviceHandle,
    DiDeviceInfo,
    DInputError,
    DirectInputApi,
    DiState,
)
from wardogs_flight_eng.inputs.dinput_match import (
    match_sdl_guid,
    vid_pid_from_sdl_guid,
)
from wardogs_flight_eng.inputs.protocol import (
    DeviceLostError,
    InputConfigError,
    InputDevice,
)
from wardogs_flight_eng.outputs.haptic_axes import HapticAxisMap

__all__ = [
    "LOST_CODES",
    "DInputJoystick",
    "checked",
    "ff_actuator_check",
    "match_sdl_guid",
    "open_dinput_joystick",
    "vid_pid_from_sdl_guid",
]

log = logging.getLogger(__name__)

FULL_GAIN = 10000
RAW_HALF_SCALE = 32767.5  # raw 0..65535 -> -1..1
LOST_CODES = frozenset({DIERR_INPUTLOST, DIERR_NOTACQUIRED, DIERR_UNPLUGGED})


def checked(status: int, call: str) -> int:
    """``status`` if it is a success; a lost code is ``DeviceLostError``,
    any other failure ``DInputError``, both naming ``call``."""
    if status >= 0:
        return status
    code = status & 0xFFFFFFFF
    if status in LOST_CODES:
        raise DeviceLostError(f"DirectInput {call}: device lost ({code:#010x})")
    raise DInputError(f"DirectInput {call} failed: {code:#010x}")


def _state_slot(axis: DiAxisInfo) -> int | None:
    """Where ``axis`` sits in ``DiState.axes``, or None when it is not there."""
    if axis.offset in DIJOFS_BY_INDEX:
        return DIJOFS_BY_INDEX.index(axis.offset)
    return None


class DInputJoystick(InputDevice):
    """An acquired DirectInput device; ``api`` and ``handle`` serve the force side.

    The constructor polls once to learn ``button_count``. ``poll`` turns the
    lost codes into ``alive = False`` plus ``DeviceLostError``; after
    ``close`` reads return 0.0 / False and the device is never touched again.
    """

    def __init__(
        self,
        api: DirectInputApi,
        handle: DiDeviceHandle,
        info: DiDeviceInfo,
        sdl_guid: str,
    ) -> None:
        self.api = api
        self.handle = handle
        self.name = info.instance_name
        self.guid = sdl_guid
        self.axes_info = sorted(api.axes(handle), key=lambda a: a.offset)
        self._slots = [_state_slot(axis) for axis in self.axes_info]
        self.axis_count = len(self.axes_info)
        self.alive = True
        self._closed = False
        self._state = DiState((), ())
        self.poll()
        self.button_count = len(self._state.buttons)

    def poll(self) -> None:
        if self._closed:
            return
        status, state = self.api.poll_state(self.handle)
        if status in LOST_CODES:
            self.alive = False
        checked(status, "poll_state")
        self._state = state

    def axis(self, index: int) -> float:
        if self._closed:
            return 0.0
        slot = self._slots[index]
        if slot is None:
            info = self.axes_info[index]
            raise InputConfigError(
                f"axis {index} ({info.name}, offset {info.offset}) is not in "
                f"the joystick state; bind one of the first eight axes"
            )
        raw = self._state.axes[slot] / RAW_HALF_SCALE - 1.0
        return max(-1.0, min(1.0, raw))

    def button(self, index: int) -> bool:
        if self._closed:
            return False
        return self._state.buttons[index]

    def close(self) -> None:
        """Unacquire and release; idempotent, and quiet on a lost device."""
        if self._closed:
            return
        self._closed = True
        self.alive = False
        status = self.api.unacquire(self.handle)
        if status < 0:
            log.info("DirectInput unacquire on close: %#010x", status & 0xFFFFFFFF)
        self.api.release_device(self.handle)


def _prepare(api: DirectInputApi, handle: DiDeviceHandle) -> None:
    """The set-up calls between ``CreateDevice`` and the first poll."""
    checked(
        api.set_cooperative_exclusive_background(handle),
        "set_cooperative_exclusive_background",
    )
    checked(api.set_autocenter_off(handle), "set_autocenter_off")
    checked(api.set_ff_gain(handle, FULL_GAIN), "set_ff_gain")
    checked(api.acquire(handle), "acquire")
    checked(api.ff_command(handle, api.DISFFC_RESET), "ff_command(DISFFC_RESET)")
    checked(
        api.ff_command(handle, api.DISFFC_SETACTUATORSON),
        "ff_command(DISFFC_SETACTUATORSON)",
    )


def open_dinput_joystick(api: DirectInputApi, sdl_guid: str) -> DInputJoystick:
    """Match ``sdl_guid``, open and acquire it; the device is released again
    if any step after ``CreateDevice`` fails."""
    info = match_sdl_guid(sdl_guid, api.enumerate_devices())
    handle = api.open_device(info.instance_guid)
    try:
        _prepare(api, handle)
        joystick = DInputJoystick(api, handle, info, sdl_guid)
    except (DInputError, DeviceLostError):
        api.release_device(handle)
        raise
    log.info("DirectInput %r opened for SDL GUID %s", info.instance_name, sdl_guid)
    return joystick


def ff_actuator_check(joystick: DInputJoystick, axis_map: HapticAxisMap) -> None:
    """Pitch and roll must each be a ``DIDOI_FFACTUATOR`` axis object."""
    for name, entry in (("pitch", axis_map.pitch), ("roll", axis_map.roll)):
        index = entry.haptic_index
        if index >= joystick.axis_count:
            raise InputConfigError(
                f"{name} is bound to axis {index}, but {joystick.name} has "
                f"{joystick.axis_count} DirectInput axes"
            )
        axis = joystick.axes_info[index]
        if not axis.ff_actuator:
            raise InputConfigError(
                f"{name} is bound to axis {index} ({axis.name}), which is not a "
                f"force-feedback actuator on {joystick.name}"
            )
