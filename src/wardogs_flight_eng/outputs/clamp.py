"""Safety ceiling applied in front of any backend.

Each command is clamped on its own; same-axis commands are never summed here
(the device sums them, which is why the ceiling is a per-command limit).
"""

import logging
from collections.abc import Sequence
from dataclasses import replace

from wardogs_flight_eng.engine.commands import (
    Command,
    PulseCommand,
    SineCommand,
    SpringCommand,
    TransientCommand,
)
from wardogs_flight_eng.outputs.protocol import ForceBackend

logger = logging.getLogger(__name__)


class ClampedBackend:
    """Wraps a backend and caps every command's strength at ``ceiling``.

    ``ceiling`` is the normalised fraction (0, 1] of the base's peak torque
    the user allows. Spring coefficients and sine/transient magnitudes are
    held to ``[0, ceiling]``; pulse magnitudes to ``[-ceiling, ceiling]`` so
    the push direction survives.
    """

    def __init__(self, inner: ForceBackend, ceiling: float) -> None:
        if not 0.0 < ceiling <= 1.0:
            raise ValueError(f"ceiling must be in (0, 1], got {ceiling!r}")
        self._inner = inner
        self.ceiling = ceiling

    def apply(self, t: float, commands: Sequence[Command]) -> None:
        self._inner.apply(t, [self._clamp(command) for command in commands])

    def all_off(self) -> None:
        self._inner.all_off()

    def close(self) -> None:
        self._inner.close()

    def _clamp(self, command: Command) -> Command:
        match command:
            case SpringCommand(coefficient=value):
                limited = self._limit(value)
                clamped: Command = replace(command, coefficient=limited)
            case SineCommand(magnitude=value) | TransientCommand(magnitude=value):
                limited = self._limit(value)
                clamped = replace(command, magnitude=limited)
            case PulseCommand(magnitude=value):
                limited = min(max(value, -self.ceiling), self.ceiling)
                clamped = replace(command, magnitude=limited)
            case _:
                return command
        if limited == value:
            return command
        logger.debug("clamped %s %.3f -> %.3f", type(command).__name__, value, limited)
        return clamped

    def _limit(self, value: float) -> float:
        return min(max(value, 0.0), self.ceiling)
