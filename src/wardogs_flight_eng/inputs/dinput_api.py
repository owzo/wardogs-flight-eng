"""The DirectInput 8 seam: the calls this package makes, plus struct mirrors.

Every DirectInput call goes through a ``DirectInputApi`` object so tests substitute
a fake; the real adapter is the ctypes COM binding in ``dinput_real``. Calls return
DirectInput's ``HRESULT`` status as a signed 32-bit int (``< 0`` = failure) but use
Python types: GUIDs are their ``{xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx}`` text,
device and effect handles are opaque objects, and effects are the ``DiEffect``
mirror below, which the real adapter converts to a genuine ``DIEFFECT``. Units are
DirectInput's: ±10000 magnitudes, coefficients and offsets; 0..10000 saturation,
dead band and gain; microseconds for durations and periods; phase in 1/100 degree.
"""

from dataclasses import dataclass
from typing import Literal, Protocol, get_args

DiGuid = str
DiDeviceHandle = object
EffectKind = Literal["spring", "damper", "inertia", "friction", "sine", "constant"]

EFFECT_KINDS: tuple[EffectKind, ...] = get_args(EffectKind)
CONDITION_KINDS: frozenset[EffectKind] = frozenset(
    {"spring", "damper", "inertia", "friction"}
)

# HRESULTs from dinput.h, as signed 32-bit values so ``< 0`` means failure.
DI_OK = 0
DI_EFFECTRESTARTED = 0x00000004
DIERR_INPUTLOST = 0x8007001E - (1 << 32)
DIERR_NOTACQUIRED = 0x8007000C - (1 << 32)
DIERR_UNPLUGGED = 0x80040209 - (1 << 32)
DIERR_EFFECTPLAYING = 0x80040208 - (1 << 32)
DIERR_DEVICENOTREG = 0x80040154 - (1 << 32)  # REGDB_E_CLASSNOTREG
DIERR_INVALIDPARAM = 0x80070057 - (1 << 32)  # E_INVALIDARG
DIERR_UNSUPPORTED = 0x80004001 - (1 << 32)  # E_NOTIMPL

# IDirectInputDevice8::SendForceFeedbackCommand commands.
DISFFC_RESET = 0x00000001
DISFFC_STOPALL = 0x00000002
DISFFC_SETACTUATORSON = 0x00000010

# DIJOYSTATE2 byte offsets of X, Y, Z, RX, RY, RZ, slider 0 and slider 1.
DIJOFS_BY_INDEX: tuple[int, ...] = (0, 4, 8, 12, 16, 20, 24, 28)


class DInputError(RuntimeError):
    """A DirectInput call failed for a reason other than the device going away."""


@dataclass(frozen=True, slots=True)
class DiDeviceInfo:
    """One attached game controller as ``EnumDevices`` reports it.

    ``product_guid``'s ``Data1`` is ``(pid << 16) | vid``.
    """

    instance_guid: DiGuid
    product_guid: DiGuid
    vid: int
    pid: int
    instance_name: str
    product_name: str
    force_feedback: bool


@dataclass(frozen=True, slots=True)
class DiAxisInfo:
    """One axis object: ``dwOfs`` in ``DIJOYSTATE2``, name, ``DIDOI_FFACTUATOR``."""

    offset: int
    name: str
    ff_actuator: bool


@dataclass(frozen=True, slots=True)
class DiCondition:
    """Mirror of ``DICONDITION`` (``offset`` is the centre, ``lOffset``)."""

    offset: int
    positive_coefficient: int
    negative_coefficient: int
    positive_saturation: int
    negative_saturation: int
    dead_band: int


@dataclass(frozen=True, slots=True)
class DiPeriodic:
    """Mirror of ``DIPERIODIC`` (``phase`` 0..35999, ``period_us`` µs)."""

    magnitude: int
    offset: int
    phase: int
    period_us: int


@dataclass(frozen=True, slots=True)
class DiConstant:
    """Mirror of ``DICONSTANTFORCE`` (signed ``lMagnitude``)."""

    magnitude: int


@dataclass(frozen=True, slots=True)
class DiEnvelope:
    """Mirror of ``DIENVELOPE`` (levels 0..10000, times in µs)."""

    attack_level: int
    attack_time_us: int
    fade_level: int
    fade_time_us: int


@dataclass(frozen=True, slots=True)
class DiEffect:
    """Mirror of ``DIEFFECT`` with the type-specific block ``kind`` selects.

    ``axes`` are ``DIJOFS_*`` offsets with one ``direction`` entry each;
    condition kinds carry one ``DiCondition`` or one per axis, ``sine`` a
    ``periodic`` block and ``constant`` a ``constant`` block.
    """

    kind: EffectKind
    axes: tuple[int, ...]
    direction: tuple[int, ...]
    duration_us: int
    gain: int
    condition: tuple[DiCondition, ...] = ()
    periodic: DiPeriodic | None = None
    constant: DiConstant | None = None
    envelope: DiEnvelope | None = None

    def __post_init__(self) -> None:
        if not self.axes or len(self.direction) != len(self.axes):
            raise ValueError(
                f"{self.kind}: direction needs one entry per axis, "
                f"got {len(self.direction)} for {len(self.axes)} axes"
            )
        condition = self.kind in CONDITION_KINDS
        carried = (
            bool(self.condition),
            self.periodic is not None,
            self.constant is not None,
        )
        if carried != (condition, self.kind == "sine", self.kind == "constant"):
            raise ValueError(f"{self.kind}: type-specific payload does not match")
        if condition and len(self.condition) not in (1, len(self.axes)):
            raise ValueError(f"{self.kind}: payload needs 1 or one condition per axis")


@dataclass(frozen=True, slots=True)
class DiState:
    """One ``GetDeviceState(DIJOYSTATE2)`` reading.

    ``axes`` are the eight axis values in ``DIJOFS_BY_INDEX`` order, raw
    0..65535 once the data format's range property is set; ``buttons`` are
    ``rgbButtons`` as pressed flags.
    """

    axes: tuple[int, ...]
    buttons: tuple[bool, ...]


class DirectInputApi(Protocol):
    """The DirectInput 8 constants and calls the input and force layers use.

    ``enumerate_devices`` lists attached game controllers; ``open_device``
    raises ``DInputError`` when ``CreateDevice`` fails; ``axes`` lists the
    axis objects in ``dwOfs`` order (``EnumObjects(DIDFT_AXIS)``);
    ``poll_state`` is ``Poll`` then ``GetDeviceState``. Every other
    status-bearing call returns its ``HRESULT``.
    """

    DISFFC_RESET: int
    DISFFC_STOPALL: int
    DISFFC_SETACTUATORSON: int

    def enumerate_devices(self) -> list[DiDeviceInfo]: ...
    def open_device(self, instance_guid: DiGuid) -> DiDeviceHandle: ...
    def axes(self, dev: DiDeviceHandle) -> list[DiAxisInfo]: ...
    def set_cooperative_exclusive_background(self, dev: DiDeviceHandle) -> int: ...
    def set_autocenter_off(self, dev: DiDeviceHandle) -> int: ...
    def set_ff_gain(self, dev: DiDeviceHandle, gain: int) -> int: ...
    def get_ff_gain(self, dev: DiDeviceHandle) -> int: ...
    def acquire(self, dev: DiDeviceHandle) -> int: ...
    def unacquire(self, dev: DiDeviceHandle) -> int: ...
    def ff_command(self, dev: DiDeviceHandle, command: int) -> int: ...
    def enum_effect_kinds(self, dev: DiDeviceHandle) -> frozenset[EffectKind]: ...
    def poll_state(self, dev: DiDeviceHandle) -> tuple[int, DiState]: ...
    def create_effect(
        self, dev: DiDeviceHandle, effect: DiEffect
    ) -> tuple[int, object]: ...
    def set_parameters(
        self, effect_handle: object, effect: DiEffect, norestart: bool
    ) -> int: ...
    def start(self, effect_handle: object) -> int: ...
    def stop(self, effect_handle: object) -> int: ...
    def release_effect(self, effect_handle: object) -> None: ...
    def release_device(self, dev: DiDeviceHandle) -> None: ...
    def close(self) -> None: ...
