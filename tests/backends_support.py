"""Shared test double for output backends (reused by the runtime tests)."""

from collections.abc import Sequence

from wardogs_flight_eng.engine.commands import Command


class RecordingBackend:
    """A ``ForceBackend`` that stores every call for later assertions."""

    def __init__(self) -> None:
        self.applied: list[list[Command]] = []
        self.times: list[float] = []
        self.all_off_calls = 0
        self.closed = False

    @property
    def last(self) -> list[Command]:
        return self.applied[-1]

    def apply(self, t: float, commands: Sequence[Command]) -> None:
        self.times.append(t)
        self.applied.append(list(commands))

    def all_off(self) -> None:
        self.all_off_calls += 1

    def close(self) -> None:
        self.closed = True
