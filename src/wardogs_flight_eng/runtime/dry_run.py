"""No-hardware acceptance run: scenario -> simulated devices -> engine -> log -> plot.

Time is tick-indexed so the run is exact and never sleeps. ``run_loop`` reads
its clock once at the start of a tick (the tick time ``t``) and again inside
its slot wait, then calls ``sleep``. ``_TickClock`` therefore returns the time
of the *current* tick index on every read and advances the index only when
``sleep`` is called, once per tick: tick ``n`` always sees ``n / rate_hz``,
with no float drift from accumulating a period. The scenario is advanced to
that same time just before each device read, so a step scheduled at ``t`` is
visible to the tick at ``t`` (``Scenario.apply_until`` uses ``<=``).
"""

import logging
from pathlib import Path

from wardogs_flight_eng.constants.model import GameConstants
from wardogs_flight_eng.engine.frame import ControlFrame
from wardogs_flight_eng.engine.profile import Profile
from wardogs_flight_eng.engine.synth import FlightEngine
from wardogs_flight_eng.inputs.composite import CompositeInput
from wardogs_flight_eng.inputs.simulated import Scenario
from wardogs_flight_eng.outputs.logging_backend import LoggingBackend
from wardogs_flight_eng.runtime.loop import run_loop
from wardogs_flight_eng.runtime.plot import write_plot_html

log = logging.getLogger(__name__)

LOG_NAME = "forces.jsonl"
PLOT_NAME = "forces.html"


class _TickClock:
    """Clock for ``run_loop`` whose time is ``tick / rate_hz``; ``sleep`` ticks it."""

    def __init__(self, rate_hz: float) -> None:
        self._rate_hz = rate_hz
        self._tick = 0

    def __call__(self) -> float:
        return self._tick / self._rate_hz

    def sleep(self, _seconds: float) -> None:
        """Advance one tick instead of sleeping; the requested wait is ignored."""
        self._tick += 1


class _ScenarioInput(CompositeInput):
    """A composite input that first plays the scenario up to the clock's time."""

    def __init__(self, scenario: Scenario, clock: _TickClock) -> None:
        super().__init__(scenario.device_map, scenario.devices)
        self._scenario = scenario
        self._clock = clock

    def read(self) -> ControlFrame:
        self._scenario.apply_until(self._clock())
        return super().read()


def dry_run(
    profile: Profile,
    constants: GameConstants,
    scenario: Scenario,
    out_dir: Path,
) -> tuple[Path, Path]:
    """Run ``scenario`` through ``profile``'s engine; return (log, plot) paths.

    The loop runs ``int(duration_s * rate_hz)`` ticks with the profile's own
    watchdog, logging every command to ``out_dir/forces.jsonl``, then renders
    ``out_dir/forces.html``. ``out_dir`` is created if missing. A run that
    ends any other way than by exhausting its ticks raises ``RuntimeError``.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / LOG_NAME
    plot_path = out_dir / PLOT_NAME
    clock = _TickClock(scenario.rate_hz)
    result = run_loop(
        [FlightEngine(profile, constants)],
        _ScenarioInput(scenario, clock),
        LoggingBackend(log_path),
        rate_hz=scenario.rate_hz,
        watchdog_s=profile.safety.watchdog_s,
        clock=clock,
        sleep=clock.sleep,
        max_ticks=int(scenario.duration_s * scenario.rate_hz),
    )
    log.info("dry run: %d ticks, stopped by %s", result.ticks, result.stopped_by)
    if result.stopped_by != "max_ticks":
        raise RuntimeError(
            f"dry run ended early after {result.ticks} ticks: {result.stopped_by}"
        )
    write_plot_html(log_path, plot_path)
    return log_path, plot_path
