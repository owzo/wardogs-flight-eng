"""Fixed-rate runtime loop: input -> engine -> force backend, safely torn down.

Each tick reads one control frame, handles a PROFILE_CYCLE tap, steps the
active engine and applies its commands, then sleeps until the next slot.
Whatever ends the loop -- a stop request, the tick budget, a lost device, any
error or an interrupt -- the backend's forces are zeroed and it is released.
"""

import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from wardogs_flight_eng.engine.commands import AllOffCommand
from wardogs_flight_eng.engine.frame import Button
from wardogs_flight_eng.engine.synth import FlightEngine
from wardogs_flight_eng.inputs.composite import CompositeInput
from wardogs_flight_eng.inputs.protocol import DeviceLostError
from wardogs_flight_eng.outputs.protocol import ForceBackend

log = logging.getLogger(__name__)

StopReason = Literal["stop", "max_ticks", "device_lost", "error"]


@dataclass(frozen=True, slots=True)
class LoopResult:
    """How many ticks ran, why the loop ended and which profile was active."""

    ticks: int
    stopped_by: StopReason
    active_profile: str


class _Tick:
    """Per-run state: active engine, last frame's buttons and the slot clock."""

    def __init__(
        self,
        engines: Sequence[FlightEngine],
        backend: ForceBackend,
        rate_hz: float,
        watchdog_s: float,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self._engines = engines
        self._backend = backend
        self._period = 1.0 / rate_hz
        self._watchdog_s = watchdog_s
        self._clock = clock
        self._sleep = sleep
        self._index = 0
        self._previous_held: frozenset[Button] = frozenset()
        self._previous_t: float | None = None
        self._deadline: float | None = None
        self.count = 0

    @property
    def engine(self) -> FlightEngine:
        return self._engines[self._index]

    def run(self, source: CompositeInput) -> None:
        """One tick: read, maybe switch profile, step, apply, wait for the slot."""
        t = self._clock()
        dt = self._period if self._previous_t is None else t - self._previous_t
        self._previous_t = t
        frame = source.read()
        if Button.PROFILE_CYCLE in frame.held - self._previous_held:
            self._cycle_profile()
        self._previous_held = frame.held
        commands = self.engine.step(dt, frame)
        if not (0.0 <= dt <= self._watchdog_s):
            # The engine gates on its own profile's watchdog; the loop's is the
            # shortest of all profiles, so it overrides a laxer active engine.
            log.warning(
                "watchdog: tick gap %.3f s is outside 0..%.3f s, forces off this tick",
                dt,
                self._watchdog_s,
            )
            commands = [AllOffCommand()]
        self._backend.apply(t, commands)
        self.count += 1
        self._wait(t)

    def _cycle_profile(self) -> None:
        """Zero forces and hand control to the next engine (``take_over``)."""
        self._backend.all_off()
        outgoing = self.engine
        self._index = (self._index + 1) % len(self._engines)
        incoming = self.engine
        incoming.take_over(outgoing)
        log.info("profile switched to %s", incoming.profile.name)

    def _wait(self, t: float) -> None:
        """Sleep until the next slot; after an overrun, restart the schedule."""
        start = t if self._deadline is None else self._deadline
        self._deadline = start + self._period
        now = self._clock()
        if self._deadline < now:
            self._deadline = now
        self._sleep(max(0.0, self._deadline - now))


def _stop_reason(
    tick: _Tick, stop: Callable[[], bool], max_ticks: int | None
) -> StopReason | None:
    if stop():
        return "stop"
    if max_ticks is not None and tick.count >= max_ticks:
        return "max_ticks"
    return None


def _invalid_arguments(engines: Sequence[FlightEngine], rate_hz: float) -> str | None:
    if not engines:
        return "run_loop needs at least one engine"
    if not rate_hz > 0:
        return f"rate_hz must be positive, got {rate_hz}"
    return None


def _teardown(backend: ForceBackend) -> None:
    """Zero forces then release the device; one failing never skips the other.

    An ``Exception`` from either step is logged. A ``BaseException`` (an
    interrupt) from ``all_off`` still lets ``close`` run, then propagates.
    """
    try:
        try:
            backend.all_off()
        except Exception:
            log.exception("backend all_off failed during teardown")
    finally:
        try:
            backend.close()
        except Exception:
            log.exception("backend close failed during teardown")


def run_loop(
    engines: Sequence[FlightEngine],
    source: CompositeInput,
    backend: ForceBackend,
    *,
    rate_hz: float,
    watchdog_s: float,
    clock: Callable[[], float] = time.perf_counter,
    sleep: Callable[[float], None] = time.sleep,
    stop: Callable[[], bool] = lambda: False,
    max_ticks: int | None = None,
) -> LoopResult:
    """Drive ``engines[0]`` (PROFILE_CYCLE advances) at ``rate_hz`` until done.

    Never raises for a lost device or a failing tick: the result reports it.
    An interrupt (``BaseException``) propagates, after the same teardown; so
    does the ``ValueError`` for no engines or a non-positive ``rate_hz``.
    """
    problem = _invalid_arguments(engines, rate_hz)
    if problem is not None:
        _teardown(backend)
        raise ValueError(problem)
    tick = _Tick(engines, backend, rate_hz, watchdog_s, clock, sleep)
    stopped_by: StopReason
    try:
        while (reason := _stop_reason(tick, stop, max_ticks)) is None:
            tick.run(source)
        stopped_by = reason
    except DeviceLostError as err:
        log.error("input device lost, stopping: %s", err)
        stopped_by = "device_lost"
    except Exception:
        log.exception("runtime loop failed, stopping")
        stopped_by = "error"
    finally:
        _teardown(backend)
    return LoopResult(tick.count, stopped_by, tick.engine.profile.name)
