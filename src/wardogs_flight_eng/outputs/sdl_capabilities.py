"""Which condition effects the base reports it can play.

``SDL_HapticQuery`` returns a mask of supported effect types. A condition kind
the mask lacks is dropped: its commands never reach the base, and one WARNING
naming it is logged when the support is read, as the backend opens. A mask of
0 means SDL could not tell, so friction, damper and inertia are all treated as
unsupported, under a single WARNING; the spring, sines and pulses are
unaffected.
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


def condition_kind(command: ConditionCommand) -> str:
    """``"friction"``, ``"damper"`` or ``"inertia"``, after the command's class."""
    return _KINDS[type(command)]


def _sdl_types(api: SdlApi) -> dict[str, int]:
    """Each condition kind's SDL effect type flag."""
    return {
        "friction": api.SDL_HAPTIC_FRICTION,
        "damper": api.SDL_HAPTIC_DAMPER,
        "inertia": api.SDL_HAPTIC_INERTIA,
    }


class ConditionSupport:
    """The condition kinds a base supports, from its reported capability mask.

    The WARNINGs for missing kinds are logged once, here at construction.
    """

    def __init__(self, api: SdlApi, mask: int) -> None:
        blind = mask == 0
        missing = [
            kind for kind, flag in _sdl_types(api).items() if blind or not mask & flag
        ]
        self._missing = frozenset(missing)
        if blind:
            log.warning(
                "the base did not report its capabilities; "
                "friction, damper and inertia are disabled"
            )
            return
        for kind in missing:
            log.warning(
                "the base reports no %s primitive; the feel runs without it", kind
            )

    @classmethod
    def from_channel(cls, api: SdlApi, channel: HapticChannel) -> "ConditionSupport":
        """Query the base once through ``channel``."""
        return cls(api, channel.query())

    @property
    def missing(self) -> frozenset[str]:
        """The unsupported kinds, from ``{"friction", "damper", "inertia"}``."""
        return self._missing

    def allows(self, command: ConditionCommand) -> bool:
        """Whether ``command`` may play; silent, the warnings were logged at open."""
        return condition_kind(command) not in self._missing
