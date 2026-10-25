"""Opening the mapped input devices for ``run``, ``calibrate`` and ``record``.

Every alias opens through SDL, except the one ``open_devices`` is told to open
through DirectInput (``--backend dinput8``'s force base).
"""

import logging
from collections.abc import Iterable, Mapping
from typing import Protocol

from wardogs_flight_eng.cli_console import EXIT_DEVICE, CliError
from wardogs_flight_eng.engine.device_map import DeviceMap, DeviceRef
from wardogs_flight_eng.inputs.dinput_api import DirectInputApi
from wardogs_flight_eng.inputs.dinput_device import open_dinput_joystick
from wardogs_flight_eng.inputs.protocol import (
    DeviceLostError,
    InputConfigError,
    InputDevice,
)
from wardogs_flight_eng.inputs.sdl_api import SdlApi
from wardogs_flight_eng.inputs.sdl_device import (
    SdlDevice,
    enumerate_devices,
    open_by_guid,
)

log = logging.getLogger(__name__)


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


class OpenedDevice(InputDevice, Protocol):
    """An input device ``run`` opened and must close again."""

    def close(self) -> None: ...


def _open_dinput(name: str, ref: DeviceRef, api: DirectInputApi) -> OpenedDevice:
    """Open the base through DirectInput, matched by its SDL GUID's vid:pid."""
    if ref.guid is None:
        raise CliError(
            f"device_map.devices.{name}: --backend dinput8 needs the device's "
            "guid; DirectInput matching reads the vid:pid from the SDL GUID"
        )
    try:
        return open_dinput_joystick(api, ref.guid)
    except DeviceLostError as err:
        raise CliError(f"device {name!r}: {err}", EXIT_DEVICE) from err


def open_devices(
    device_map: DeviceMap,
    api: SdlApi | None,
    names: Iterable[str] | None = None,
    *,
    dinput_base: str | None = None,
    dinput_api: DirectInputApi | None = None,
) -> dict[str, OpenedDevice]:
    """Open ``names`` (default: every mapped device); all or none stay open.

    The alias ``dinput_base`` is opened through ``dinput_api`` and never by
    SDL (SDL would acquire it exclusively); every other alias through SDL.
    The base opens last: finding an SDL device by GUID opens and closes every
    joystick in turn, and must not meet the base acquired exclusively.
    """
    if dinput_base is not None and dinput_api is None:
        raise ValueError("dinput_base needs a dinput_api")
    wanted = list(device_map.devices if names is None else names)
    opened: dict[str, OpenedDevice] = {}
    try:
        for name in sorted(wanted, key=lambda alias: alias == dinput_base):
            ref = device_map.devices[name]
            if name == dinput_base and dinput_api is not None:
                opened[name] = _open_dinput(name, ref, dinput_api)
            else:
                opened[name] = _open_one(name, ref, api)
            log.info("opened %r: %s (%s)", name, opened[name].name, opened[name].guid)
    except BaseException:
        close_devices(opened)
        raise
    return opened


def close_devices(devices: Mapping[str, OpenedDevice]) -> None:
    for device in devices.values():
        device.close()
