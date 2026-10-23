"""TeeBackend: primary first, secondary failures logged and never raised."""

import logging
from collections.abc import Sequence

import pytest

from wardogs_flight_eng.engine.commands import AllOffCommand, Command
from wardogs_flight_eng.outputs.tee import TeeBackend

TICK: list[Command] = [AllOffCommand()]


class Ordered:
    """Appends ``(name, call)`` to a shared event list; can fail on demand."""

    def __init__(self, name: str, events: list[tuple[str, str]]) -> None:
        self._name = name
        self._events = events
        self.fail: set[str] = set()

    def _record(self, call: str) -> None:
        self._events.append((self._name, call))
        if call in self.fail:
            raise OSError(f"{self._name} {call} failed")

    def apply(self, t: float, commands: Sequence[Command]) -> None:
        self._record("apply")

    def all_off(self) -> None:
        self._record("all_off")

    def close(self) -> None:
        self._record("close")


def _pair() -> tuple[Ordered, Ordered, TeeBackend, list[tuple[str, str]]]:
    events: list[tuple[str, str]] = []
    primary, secondary = Ordered("primary", events), Ordered("secondary", events)
    return primary, secondary, TeeBackend(primary, secondary), events


def test_every_call_reaches_both_primary_first() -> None:
    _, _, tee, events = _pair()
    tee.apply(0.0, TICK)
    tee.all_off()
    tee.close()
    assert events == [
        (name, call)
        for call in ("apply", "all_off", "close")
        for name in ("primary", "secondary")
    ]


@pytest.mark.parametrize("call", ["apply", "all_off", "close"])
def test_secondary_failure_is_logged_not_raised(
    call: str, caplog: pytest.LogCaptureFixture
) -> None:
    _, secondary, tee, _ = _pair()
    secondary.fail.add(call)
    with caplog.at_level(logging.ERROR):
        if call == "apply":
            tee.apply(0.0, TICK)
        else:
            getattr(tee, call)()
    assert f"secondary backend {call} failed" in caplog.text


@pytest.mark.parametrize("call", ["all_off", "close"])
def test_primary_failure_still_reaches_secondary(call: str) -> None:
    primary, _, tee, events = _pair()
    primary.fail.add(call)
    with pytest.raises(OSError, match=f"primary {call} failed"):
        getattr(tee, call)()
    assert events == [("primary", call), ("secondary", call)]


def test_primary_apply_failure_propagates() -> None:
    primary, _, tee, events = _pair()
    primary.fail.add("apply")
    with pytest.raises(OSError):
        tee.apply(0.0, TICK)
    assert events == [("primary", "apply")]
