"""AB9 conformance through DirectInput 8; skipped unless ``WFE_HARDWARE=1`` and
``WFE_BACKEND=dinput8``.

Run with the base powered, plugged in and the stick released::

    WFE_HARDWARE=1 WFE_BACKEND=dinput8 uv run pytest tests/test_dinput_hardware.py
        -v --log-cli-level=INFO

The base is the instance matching ``WFE_SDL_GUID`` (as ``run`` matches it;
the primitive probe also runs then), else the first force-feedback
DirectInput instance. Bindings come from ``WFE_PITCH_AXIS`` /
``WFE_ROLL_AXIS`` (default 1 / 0) and ``WFE_PITCH_INVERT`` /
``WFE_ROLL_INVERT``, as in ``test_sdl_hardware`` (``dinput_hardware_support``
holds the rig and the frequency read). Everything is measured on
the base's own ``poll_state`` through ``CompositeInput``:

1. a spring at centre +0.5 (coefficient 0.3) held 2 s brings pitch to
   +0.5 +/- 0.15; a +0.3 pulse then moves pitch in the + direction; a
   5.5 Hz sine is held 2 s (range logged); friction, damper and inertia are
   reported and accepted;
2. the sine phase clock (spec ruling 8): a 5 Hz sine whose magnitude ramps
   0.1 -> 0.5 over 3 s, re-sent every 5 ms tick, must measure 5 Hz +/- 15 %
   (a phase jump per in-place send would read roughly double); and a sweep
   3 -> 6 Hz over 3 s must measure the mean commanded 4.5 Hz +/- 15 %.

``WFE_UNPLUG=1`` adds the interactive unplug check: pull the base's USB
cable when told; the next input poll must raise ``DeviceLostError``.
"""

import contextlib
import logging
import os
from collections.abc import Callable, Sequence
from statistics import mean

import pytest
from dinput_hardware_support import (
    measured_frequency,
    rig,
    run,
    sin_turns,
    steady,
)

from wardogs_flight_eng.engine.commands import (
    Axis,
    Command,
    DamperCommand,
    FrictionCommand,
    InertiaCommand,
    PulseCommand,
    SineCommand,
    SpringCommand,
)
from wardogs_flight_eng.inputs.dinput_real import RealDirectInput
from wardogs_flight_eng.inputs.protocol import DeviceLostError
from wardogs_flight_eng.outputs.dinput_probe import probe_dinput

ON_BASE = (
    os.environ.get("WFE_HARDWARE") == "1" and os.environ.get("WFE_BACKEND") == "dinput8"
)
hardware = pytest.mark.skipif(
    not ON_BASE,
    reason="DirectInput hardware test; set WFE_HARDWARE=1 WFE_BACKEND=dinput8",
)
unplug = pytest.mark.skipif(
    not ON_BASE or os.environ.get("WFE_UNPLUG") != "1",
    reason="interactive unplug check; also set WFE_UNPLUG=1",
)

log = logging.getLogger(__name__)

FAST_TICK_S = 0.005  # 200 Hz: a new SineCommand every tick
HOLD_S = 2.0
SWEEP_S = 3.0
SPRING = SpringCommand(Axis.PITCH, 0.5, 0.3, 0.0)
CENTRING = SpringCommand(Axis.PITCH, 0.0, 0.2, 0.0)
CENTER_TOLERANCE = 0.15
PULSE = PulseCommand(Axis.PITCH, 0.3, 0.2)
MIN_PULSE_DELTA = 0.02
SINE = SineCommand(Axis.PITCH, 5.5, 0.2)
CONDITIONS = (
    FrictionCommand(Axis.PITCH, 0.2),
    DamperCommand(Axis.PITCH, 0.2),
    InertiaCommand(Axis.PITCH, 0.2),
)
FREQUENCY_TOLERANCE = 0.15
UNPLUG_WAIT_S = 20.0


@hardware
def test_spring_pulse_sine_and_conditions() -> None:
    guid = os.environ.get("WFE_SDL_GUID")
    if guid:
        api = RealDirectInput()
        try:
            report, detail = probe_dinput(api, guid)
        finally:
            api.close()
        log.info("probe: %s, gain %d", report, detail.ff_gain)
        assert report.spring and report.spring_center_moves
        assert report.sine and report.constant
    with rig() as base:
        backend = base.backend
        held = run(base, HOLD_S, steady(SPRING))[1][-1]
        log.info("spring centre +0.5: pitch reads %+.3f", held)
        assert abs(held - SPRING.center) <= CENTER_TOLERANCE

        pushed = run(base, PULSE.duration_s, steady(SPRING), first=[PULSE])[1]
        delta = mean(pushed[len(pushed) // 2 :]) - held
        log.info("pulse +%.1f: pitch delta %+.3f", PULSE.magnitude, delta)
        assert delta > MIN_PULSE_DELTA

        buzz = run(base, HOLD_S, steady(SPRING, SINE))[1]
        swing = max(buzz) - min(buzz)
        log.info("sine %.1f Hz: pitch range %.3f", SINE.frequency_hz, swing)

        log.info("missing conditions: %s", sorted(backend.missing_conditions))
        assert not backend.missing_conditions
        run(base, 0.5, steady(SPRING, *CONDITIONS))
        backend.all_off()


def _sine_clock_check(
    every: Callable[[float], Sequence[Command]], nominal_hz: float, what: str
) -> None:
    with rig() as base:
        times, trace = run(base, SWEEP_S, every, tick_s=FAST_TICK_S)
        base.backend.all_off()
    measured = measured_frequency(times, trace, nominal_hz)
    log.info("%s: measured %.2f Hz (expected %.2f Hz)", what, measured, nominal_hz)
    assert abs(measured - nominal_hz) <= FREQUENCY_TOLERANCE * nominal_hz


@hardware
def test_sine_phase_survives_a_magnitude_ramp() -> None:
    def every(fraction: float) -> Sequence[Command]:
        return CENTRING, SineCommand(Axis.PITCH, 5.0, 0.1 + 0.4 * fraction)

    _sine_clock_check(every, 5.0, "5 Hz sine, magnitude 0.1 -> 0.5")


@hardware
def test_sine_phase_survives_a_frequency_sweep() -> None:
    def every(fraction: float) -> Sequence[Command]:
        return CENTRING, SineCommand(Axis.PITCH, 3.0 + 3.0 * fraction, 0.3)

    _sine_clock_check(every, 4.5, "sine 3 -> 6 Hz, magnitude 0.3")


@unplug
def test_unplugging_the_base_is_device_lost() -> None:
    with contextlib.suppress(DeviceLostError), rig() as base:
        log.warning("unplug the base's USB cable now (%.0f s)", UNPLUG_WAIT_S)
        with pytest.raises(DeviceLostError):
            run(base, UNPLUG_WAIT_S, steady(CENTRING))
        log.info("device lost raised")


def test_frequency_estimator_reads_a_drifting_ramped_sine() -> None:
    times = [i * FAST_TICK_S for i in range(600)]
    noise = [0.01 * sin_turns(97.0 * t) for t in times]
    trace = [
        (0.1 + 0.4 * t / 3.0) * sin_turns(5.0 * t + 0.1) + 0.2 * t + n
        for t, n in zip(times, noise, strict=True)
    ]
    assert measured_frequency(times, trace, 5.0) == pytest.approx(5.0, rel=0.05)


def test_frequency_estimator_tells_a_doubled_sine_apart() -> None:
    times = [i * FAST_TICK_S for i in range(600)]
    doubled = [(0.1 + 0.4 * t / 3.0) * sin_turns(10.0 * t) for t in times]
    measured = measured_frequency(times, doubled, 5.0)
    assert abs(measured - 5.0) > FREQUENCY_TOLERANCE * 5.0


def test_frequency_estimator_reads_the_mean_of_a_sweep() -> None:
    times = [i * FAST_TICK_S for i in range(600)]
    trace = [0.3 * sin_turns(3.0 * t + 0.5 * t * t) for t in times]  # 3 -> 6 Hz
    assert measured_frequency(times, trace, 4.5) == pytest.approx(4.5, rel=0.05)
