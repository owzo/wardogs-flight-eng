"""Ctrl+C during ``run``, and whether the force base was really released."""

import logging
import signal
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from types import FrameType
from typing import Final

from wardogs_flight_eng.engine.commands import Command
from wardogs_flight_eng.outputs.protocol import ForceBackend

log = logging.getLogger(__name__)

CTRL_C_GRACE_S: Final = 3.0
"""After the first Ctrl+C, further presses are ignored for this long."""


@contextmanager
def ctrl_c_requests_stop(
    clock: Callable[[], float] = time.monotonic,
) -> Iterator[threading.Event]:
    """While active, Ctrl+C asks the loop to stop rather than interrupting it.

    The first press sets the returned event: the loop finishes its tick and
    tears down. Presses within ``CTRL_C_GRACE_S`` of the first are logged and
    ignored, so they cannot cut the teardown short. A press after that
    deadline raises ``KeyboardInterrupt`` (as the default handler would), so
    a hung tick can still be escaped; the loop's teardown runs even then.
    The previous handler is restored on exit.
    """
    requested = threading.Event()
    first_press: list[float] = []

    def on_ctrl_c(_signum: int, _frame: FrameType | None) -> None:
        if not first_press:
            first_press.append(clock())
            requested.set()
            log.info("Ctrl+C: stopping after this tick")
            return
        if clock() - first_press[0] < CTRL_C_GRACE_S:
            log.warning("Ctrl+C: already stopping, releasing the base")
            return
        raise KeyboardInterrupt

    if threading.current_thread() is not threading.main_thread():
        yield requested  # signals reach only the main thread
        return
    previous = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, on_ctrl_c)
    try:
        yield requested
    finally:
        restored = signal.default_int_handler if previous is None else previous
        signal.signal(signal.SIGINT, restored)


class ReleaseWatch:
    """``ForceBackend`` pass-through recording whether ``close`` completed.

    ``released`` is True only once the wrapped chain's ``close`` returned
    normally, so the CLI never claims a release that did not happen.
    """

    def __init__(self, inner: ForceBackend) -> None:
        self._inner = inner
        self.close_attempted = False
        self.released = False

    def apply(self, t: float, commands: Sequence[Command]) -> None:
        self._inner.apply(t, commands)

    def all_off(self) -> None:
        self._inner.all_off()

    def close(self) -> None:
        self.close_attempted = True
        self._inner.close()
        self.released = True
