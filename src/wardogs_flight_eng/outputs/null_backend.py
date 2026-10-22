"""A backend that discards everything (dry runs and device-less sessions)."""

from collections.abc import Sequence

from wardogs_flight_eng.engine.commands import Command


class NullBackend:
    """Accepts every call and does nothing."""

    def apply(self, t: float, commands: Sequence[Command]) -> None:
        return None

    def all_off(self) -> None:
        return None

    def close(self) -> None:
        return None
