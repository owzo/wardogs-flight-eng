"""Helpers for the DirectInput haptic backend tests (built on the fake DirectInput)."""

from dataclasses import replace

from dinput_support import FakeDiDevice, FakeDirectInput, ab9

from wardogs_flight_eng.engine.commands import Axis, Command, SineCommand, SpringCommand
from wardogs_flight_eng.engine.device_map import (
    AxisBinding,
    Calibration,
    DeviceMap,
    DeviceRef,
)
from wardogs_flight_eng.inputs.composite import CompositeInput
from wardogs_flight_eng.inputs.dinput_api import DISFFC_STOPALL, DiEffect, EffectKind
from wardogs_flight_eng.inputs.dinput_device import DInputJoystick, open_dinput_joystick
from wardogs_flight_eng.inputs.protocol import InputDevice
from wardogs_flight_eng.inputs.simulated import SimulatedDevice
from wardogs_flight_eng.outputs.dinput_haptic import DInputHapticBackend
from wardogs_flight_eng.outputs.haptic_axes import HapticAxisMap

PITCH_OFFSET = 4  # DIJOFS_Y: STANDARD_AXES puts pitch on axis 1
ROLL_OFFSET = 0  # DIJOFS_X: roll on axis 0
SINE_5_5 = 181597  # µs: round(1e6 / 5.5067)
SINE_6 = 166667  # µs: round(1e6 / 6.0)
STOP_ALL = ("ff_command", (DISFFC_STOPALL,))

STANDARD_AXES = HapticAxisMap.from_bindings(
    pitch=AxisBinding(device="stick", axis=1), roll=AxisBinding(device="stick", axis=0)
)


def _le16(value: int) -> str:
    return f"{value & 0xFF:02x}{value >> 8:02x}"


def sdl_guid(device: FakeDiDevice) -> str:
    """The Windows SDL GUID string of ``device`` (LE vendor, LE product)."""
    return f"0300ab9c{_le16(device.vid)}0000{_le16(device.pid)}000000000000"


def open_joystick(fake: FakeDirectInput) -> DInputJoystick:
    return open_dinput_joystick(fake, sdl_guid(fake.devices[0]))


def open_backend(
    fake: FakeDirectInput,
    length_s: float = 1.0,
    axis_map: HapticAxisMap = STANDARD_AXES,
) -> DInputHapticBackend:
    """Open the fake's first device and build the backend on it.

    The open sequence is cleared from ``fake.calls``, so tests see only the
    calls the backend makes.
    """
    backend = DInputHapticBackend(open_joystick(fake), length_s, axis_map=axis_map)
    fake.calls.clear()
    return backend


def fresh(
    length_s: float = 1.0,
    axis_map: HapticAxisMap = STANDARD_AXES,
    device: FakeDiDevice | None = None,
) -> tuple[FakeDirectInput, DInputHapticBackend]:
    """A fake over ``device`` (default ``ab9()``) and a backend opened on it."""
    fake = FakeDirectInput(ab9() if device is None else device)
    return fake, open_backend(fake, length_s, axis_map)


def created(fake: FakeDirectInput) -> list[tuple[int, DiEffect]]:
    found: list[tuple[int, DiEffect]] = []
    for effect_id, effect in fake.args("create_effect"):
        assert isinstance(effect_id, int) and isinstance(effect, DiEffect)
        found.append((effect_id, effect))
    return found


def updates(fake: FakeDirectInput) -> list[tuple[int, DiEffect, bool]]:
    """Every ``set_parameters``: (effect id, effect, ``norestart``)."""
    found: list[tuple[int, DiEffect, bool]] = []
    for effect_id, effect, norestart in fake.args("set_parameters"):
        assert isinstance(effect_id, int) and isinstance(effect, DiEffect)
        assert isinstance(norestart, bool)
        found.append((effect_id, effect, norestart))
    return found


def per_effect(fake: FakeDirectInput, name: str) -> dict[int, int]:
    """How many ``name`` calls each effect id received."""
    counts: dict[int, int] = {}
    for args in fake.args(name):
        effect_id = args[0]
        assert isinstance(effect_id, int)
        counts[effect_id] = counts.get(effect_id, 0) + 1
    return counts


def released_ids(fake: FakeDirectInput) -> list[int]:
    ids = [effect_id for (effect_id,) in fake.args("release_effect")]
    return sorted(effect_id for effect_id in ids if isinstance(effect_id, int))


def last_effect(fake: FakeDirectInput, kind: EffectKind) -> DiEffect:
    """The newest live effect of ``kind`` (its current parameters)."""
    return next(e for e in reversed(fake.effects.values()) if e.kind == kind)


def periodic_phases(fake: FakeDirectInput) -> list[int]:
    """The phase of every sine sent through ``set_parameters``, in order."""
    return [
        effect.periodic.phase
        for _, effect, _ in updates(fake)
        if effect.periodic is not None
    ]


def steady_tick() -> list[Command]:
    return [
        SpringCommand(Axis.PITCH, 0.25, 0.35, 0.02),
        SpringCommand(Axis.ROLL, 0.0, 0.3, 0.02),
        SineCommand(Axis.PITCH, 5.5067, 0.4),
        SineCommand(Axis.ROLL, 5.5067, 0.4),
    ]


def stiffer_tick() -> list[Command]:
    """``steady_tick`` with the pitch spring centred at 0.3 instead of 0.25."""
    return [
        replace(c, center=0.3)
        if isinstance(c, SpringCommand) and c.axis == Axis.PITCH
        else c
        for c in steady_tick()
    ]


def base_source(base: DInputJoystick) -> CompositeInput:
    """Pitch and roll on the DirectInput base; collective and pedals simulated."""
    devices: dict[str, InputDevice] = {
        "base": base,
        "coll": SimulatedDevice("coll", axis_count=1),
        "ped": SimulatedDevice("ped", axis_count=1),
    }
    refs = {name: DeviceRef(guid=d.guid, product=None) for name, d in devices.items()}
    device_map = DeviceMap(
        devices=refs,
        axes={
            "pitch": AxisBinding(device="base", axis=1),
            "roll": AxisBinding(device="base", axis=0),
            "collective": AxisBinding(device="coll", axis=0),
            "pedals": AxisBinding(device="ped", axis=0),
        },
        buttons={},
        calibration=Calibration(),
    )
    return CompositeInput(device_map, devices)
