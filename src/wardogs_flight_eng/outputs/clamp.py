"""Safety ceiling applied in front of any backend.

Each command is clamped on its own; same-axis commands are never summed here
(the device sums them, which is why the ceiling is a per-command limit).
"""

import logging
import math
from collections.abc import Sequence
from dataclasses import replace
from typing import assert_never

from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Axis,
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
    the push direction survives. A non-finite value (NaN or +/-inf) fails
    closed: it is replaced by 0.0, never passed through and never raised.
    """

    def __init__(self, inner: ForceBackend, ceiling: float) -> None:
        if not 0.0 < ceiling <= 1.0:
            raise ValueError(f"ceiling must be in (0, 1], got {ceiling!r}")
        self._inner = inner
        self._ceiling = ceiling
        self._warned: set[tuple[Axis, str]] = set()

    @property
    def ceiling(self) -> float:
        return self._ceiling

    def apply(self, t: float, commands: Sequence[Command]) -> None:
        self._inner.apply(t, [self._clamp(command) for command in commands])

    def all_off(self) -> None:
        self._inner.all_off()

    def close(self) -> None:
        self._inner.close()

    def _clamp(self, command: Command) -> Command:
        match command:
            case AllOffCommand():
                return command
            case SpringCommand(coefficient=value):
                limited = self._limit(value, 0.0)
                if self._unchanged(command, value, limited):
                    return command
                return replace(command, coefficient=limited)
            case SineCommand(magnitude=value) | TransientCommand(magnitude=value):
                limited = self._limit(value, 0.0)
                if self._unchanged(command, value, limited):
                    return command
                return replace(command, magnitude=limited)
            case PulseCommand(magnitude=value):
                limited = self._limit(value, -self._ceiling)
                if self._unchanged(command, value, limited):
                    return command
                return replace(command, magnitude=limited)
            case _:
                assert_never(command)

    def _limit(self, value: float, floor: float) -> float:
        if not math.isfinite(value):
            return 0.0
        return min(max(value, floor), self._ceiling)

    def _unchanged(
        self,
        command: SpringCommand | SineCommand | PulseCommand | TransientCommand,
        value: float,
        limited: float,
    ) -> bool:
        """Return True when no clamp was needed; otherwise log the clamp.

        Non-finite values warn every time (they should never occur). A finite
        clamp warns once per (axis, command kind), then logs at DEBUG, so a
        profile that sits above the ceiling does not flood the log each tick.
        """
        if limited == value:
            return True
        kind = type(command).__name__
        if not math.isfinite(value):
            logger.warning("non-finite value in %s replaced by %.1f", kind, limited)
            return False
        key = (command.axis, kind)
        first = key not in self._warned
        self._warned.add(key)
        if first:
            logger.warning(
                "clamped %s on %s from %.3f to %.3f; further clamps of this kind"
                " are logged at DEBUG",
                kind,
                command.axis,
                value,
                limited,
            )
        else:
            logger.debug(
                "clamped %s on %s from %.3f to %.3f", kind, command.axis, value, limited
            )
        return False
