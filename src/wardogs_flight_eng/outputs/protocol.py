"""Contract every force-feedback output backend implements."""

from collections.abc import Sequence
from typing import Protocol

from wardogs_flight_eng.engine.commands import Command


class ForceBackend(Protocol):
    """Applies the engine's per-tick commands to a device (or a log).

    ``apply`` receives the simulation time ``t`` in seconds and the commands
    for that tick. ``all_off`` stops every effect immediately; ``close``
    releases resources and may be called more than once.
    """

    def apply(self, t: float, commands: Sequence[Command]) -> None: ...

    def all_off(self) -> None: ...

    def close(self) -> None: ...
