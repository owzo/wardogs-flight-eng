"""Which condition effects the DirectInput base reports it can play.

``EnumEffects`` lists the effect kinds the base supports. A condition kind it
lacks is dropped: its commands never reach the base, and one WARNING naming
it is logged when the support is read, as the backend opens. An empty list
means the base did not tell, so friction, damper and inertia are all treated
as unsupported, under a single WARNING; the spring, sines and pulses are
unaffected. The texts match the SDL backend's.
"""

import logging

from wardogs_flight_eng.engine.commands import ConditionCommand
from wardogs_flight_eng.inputs.dinput_api import (
    DiDeviceHandle,
    DirectInputApi,
    EffectKind,
)
from wardogs_flight_eng.outputs.dinput_effects import condition_kind

log = logging.getLogger(__name__)

_GATED_KINDS: tuple[EffectKind, ...] = ("friction", "damper", "inertia")


class DInputConditionSupport:
    """The condition kinds a base supports, from its enumerated effect kinds.

    The WARNINGs for missing kinds are logged once, here at construction.
    """

    def __init__(self, kinds: frozenset[EffectKind]) -> None:
        blind = not kinds
        missing = [kind for kind in _GATED_KINDS if blind or kind not in kinds]
        self._missing: frozenset[str] = frozenset(missing)
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
    def from_device(
        cls, api: DirectInputApi, dev: DiDeviceHandle
    ) -> "DInputConditionSupport":
        """Enumerate the base's effect kinds once."""
        return cls(api.enum_effect_kinds(dev))

    @property
    def missing(self) -> frozenset[str]:
        """The unsupported kinds, from ``{"friction", "damper", "inertia"}``."""
        return self._missing

    def allows(self, command: ConditionCommand) -> bool:
        """Whether ``command`` may play; silent, the warnings were logged at open."""
        return condition_kind(command) not in self._missing
