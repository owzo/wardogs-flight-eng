"""Send every backend call to a primary backend and a secondary observer."""

import logging
from collections.abc import Callable, Sequence

from wardogs_flight_eng.engine.commands import Command
from wardogs_flight_eng.outputs.protocol import ForceBackend

log = logging.getLogger(__name__)


class TeeBackend:
    """``ForceBackend`` forwarding each call to ``primary``, then ``secondary``.

    The primary (the device) always goes first and its failures propagate.
    The secondary (a force log) is best effort: a failure there is logged
    and never raised, so a full disk cannot stop forces being zeroed. A
    failing primary ``all_off`` or ``close`` still reaches the secondary, so
    the log is flushed and closed whatever the device does.
    """

    def __init__(self, primary: ForceBackend, secondary: ForceBackend) -> None:
        self._primary = primary
        self._secondary = secondary

    def apply(self, t: float, commands: Sequence[Command]) -> None:
        self._primary.apply(t, commands)
        self._observe("apply", lambda: self._secondary.apply(t, commands))

    def all_off(self) -> None:
        try:
            self._primary.all_off()
        finally:
            self._observe("all_off", self._secondary.all_off)

    def close(self) -> None:
        try:
            self._primary.close()
        finally:
            self._observe("close", self._secondary.close)

    @staticmethod
    def _observe(call: str, action: Callable[[], None]) -> None:
        try:
            action()
        except Exception:
            log.exception("secondary backend %s failed; continuing", call)
