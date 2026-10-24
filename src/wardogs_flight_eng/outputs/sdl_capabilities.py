"""Which condition effects the base reports it can play.

``SDL_HapticQuery`` returns a mask of supported effect types. A condition kind
the mask lacks is dropped: its commands never reach the base and one WARNING
names it the first time one arrives. A mask of 0 means SDL could not tell, so
friction, damper and inertia are all treated as unsupported, under a single
WARNING; the spring, sines and pulses are unaffected.
"""

import logging

from wardogs_flight_eng.engine.commands import (
    ConditionCommand,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
)
from wardogs_flight_eng.inputs.sdl_api import SdlApi
from wardogs_flight_eng.outputs.sdl_channel import HapticChannel

log = logging.getLogger(__name__)

_KINDS: dict[type, str] = {
    FrictionCommand: "friction",
    DamperCommand: "damper",
    InertiaCommand: "inertia",
}
_SDL_TYPES = {
    "friction": "SDL_HAPTIC_FRICTION",
    "damper": "SDL_HAPTIC_DAMPER",
    "inertia": "SDL_HAPTIC_INERTIA",
}


def condition_kind(command: ConditionCommand) -> str:
    """``"friction"``, ``"damper"`` or ``"inertia"``, after the command's class."""
    return _KINDS[type(command)]


class ConditionSupport:
    """The condition kinds a base supports, from its reported capability mask."""

    def __init__(self, api: SdlApi, mask: int) -> None:
        self._blind = mask == 0
        self._missing = frozenset(
            kind
            for kind, name in _SDL_TYPES.items()
            if self._blind or not mask & getattr(api, name)
        )
        self._warned: set[str] = set()

    @classmethod
    def from_channel(cls, api: SdlApi, channel: HapticChannel) -> "ConditionSupport":
        """Query the base once through ``channel``."""
        return cls(api, channel.query())

    @property
    def missing(self) -> frozenset[str]:
        """The unsupported kinds, from ``{"friction", "damper", "inertia"}``."""
        return self._missing

    def allows(self, command: ConditionCommand) -> bool:
        """Whether ``command`` may play; warns once per unsupported kind."""
        kind = condition_kind(command)
        if kind not in self._missing:
            return True
        if kind not in self._warned:
            self._warn(kind)
        return False

    def _warn(self, kind: str) -> None:
        if self._blind:
            log.warning(
                "the base did not report its capabilities; "
                "friction, damper and inertia are disabled"
            )
            self._warned.update(self._missing)
            return
        log.warning("the base reports no %s primitive; the feel runs without it", kind)
        self._warned.add(kind)
