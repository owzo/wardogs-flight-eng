"""DirectInput haptic backend: held effects, phase carry, all-off, loss, close."""

import logging
from dataclasses import replace

import pytest
from dinput_haptic_support import (
    SINE_5_5,
    STANDARD_AXES,
    STOP_ALL,
    base_source,
    created,
    fresh,
    open_joystick,
    per_effect,
    periodic_phases,
    released_ids,
    steady_tick,
    stiffer_tick,
    updates,
)
from dinput_support import FakeDirectInput, ab9
from loop_support import TickClock, make_engine

from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Axis,
    PulseCommand,
    SineCommand,
    TransientCommand,
)
from wardogs_flight_eng.inputs import dinput_api as di
from wardogs_flight_eng.inputs.protocol import DeviceLostError
from wardogs_flight_eng.outputs.dinput_haptic import DInputHapticBackend
from wardogs_flight_eng.outputs.dinput_sines import advance_phase
from wardogs_flight_eng.runtime.loop import run_loop

SINE = SineCommand(Axis.PITCH, 5.5067, 0.4)


def test_identical_ticks_create_once_and_restart_only_at_half_length() -> None:
    fake, backend = fresh()
    for n in range(100):
        backend.apply(n / 100, steady_tick())
    ids = [effect_id for effect_id, _ in created(fake)]
    assert ids == [0, 1, 2, 3]
    # a spring restarts as held; a sine is updated once to carry its phase
    assert [per_effect(fake, "set_parameters").get(i, 0) for i in ids] == [0, 0, 1, 1]
    assert all(per_effect(fake, "start")[i] == 2 for i in ids)  # 0 s and 0.51 s


def test_changed_spring_centre_updates_in_place_without_a_start() -> None:
    fake, backend = fresh()
    for n in range(50):
        backend.apply(n / 100, steady_tick())
    fake.calls.clear()
    backend.apply(0.5, stiffer_tick())
    assert fake.calls == [("set_parameters", (0, fake.effects[0], True))]
    assert fake.effects[0].condition[0].offset == 3000
    for n in range(51, 100):
        backend.apply(n / 100, stiffer_tick())
    assert per_effect(fake, "set_parameters")[0] == 1


def test_sine_carries_its_phase_across_starts_and_in_place_updates() -> None:
    fake, backend = fresh()
    for n in range(52):  # 0.51 s is the first tick past half the length
        backend.apply(n / 100, [SINE])
    assert periodic_phases(fake) == [advance_phase(0, 0.51, SINE_5_5)]
    assert fake.count("start") == 2
    backend.apply(0.6, [replace(SINE, magnitude=0.5)])  # in place, no start
    backend.apply(0.61, [replace(SINE, magnitude=0.5)])  # unchanged: no call
    assert periodic_phases(fake)[-1] == advance_phase(0, 0.6, SINE_5_5)
    assert (fake.count("set_parameters"), fake.count("start")) == (2, 2)


def test_period_change_in_place_rebases_the_phase_clock() -> None:
    fake, backend = fresh()
    backend.apply(0.0, [SineCommand(Axis.PITCH, 6.0, 0.4)])
    backend.apply(0.3, [SineCommand(Axis.PITCH, 5.0, 0.4)])
    backend.apply(0.6, [SineCommand(Axis.PITCH, 5.0, 0.4)])  # half-life start
    at_change = advance_phase(0, 0.3, 166667)
    assert periodic_phases(fake) == [at_change, advance_phase(at_change, 0.3, 200000)]


def test_refused_in_place_update_carries_the_phase_into_the_restart() -> None:
    fake, backend = fresh()
    fake.norestart_unsupported = True
    backend.apply(0.0, [SINE])
    backend.apply(0.1, [replace(SINE, magnitude=0.5)])  # refused, then restarted
    backend.apply(0.2, [replace(SINE, magnitude=0.6)])  # latched: restart at once
    first = advance_phase(0, 0.1, SINE_5_5)
    sent = [(e.periodic and e.periodic.phase, nr) for _, e, nr in updates(fake)]
    second = advance_phase(first, 0.1, SINE_5_5)
    assert sent == [(first, True), (first, False), (second, False)]
    assert fake.count("start") == 1


def test_all_off_stops_zeroes_and_the_next_tick_restarts() -> None:
    fake, backend = fresh()
    backend.apply(0.0, steady_tick())
    fake.calls.clear()
    backend.all_off()
    assert fake.calls[0] == STOP_ALL and fake.count("start") == 0
    zeroed = updates(fake)
    assert sorted(i for i, _, _ in zeroed) == [0, 1, 2, 3]
    assert all(e.condition[0].positive_coefficient == 0 for _, e, _ in zeroed[:2])
    assert all(e.periodic and e.periodic.magnitude == 0 for _, e, _ in zeroed[2:])
    backend.apply(0.01, steady_tick())
    assert (fake.count("set_parameters"), fake.count("start")) == (8, 4)
    assert fake.effects[0].condition[0].positive_coefficient == 3500


def test_all_off_command_stops_everything() -> None:
    fake, backend = fresh()
    backend.apply(0.0, [AllOffCommand()])
    assert fake.calls == [STOP_ALL]


def test_force_call_on_a_lost_device_raises_device_lost() -> None:
    fake, backend = fresh()
    fake.fail["start"] = di.DIERR_INPUTLOST
    with pytest.raises(DeviceLostError, match="Start"):
        backend.apply(0.0, steady_tick())


def test_detached_device_raises_device_lost_on_the_next_force_call() -> None:
    fake, backend = fresh()
    backend.apply(0.0, steady_tick())
    fake.devices[0].attached = False
    with pytest.raises(DeviceLostError):
        backend.apply(0.01, stiffer_tick())
    with pytest.raises(DeviceLostError):
        backend.all_off()


def test_other_failure_raises_dinput_error() -> None:
    fake, backend = fresh()
    fake.fail["start"] = di.DIERR_INVALIDPARAM
    with pytest.raises(di.DInputError, match="Start failed"):
        backend.apply(0.0, steady_tick())


def test_close_order_and_close_twice_releases_each_effect_once() -> None:
    fake, backend = fresh()
    backend.apply(0.0, [*steady_tick(), PulseCommand(Axis.ROLL, 0.5, 0.02)])
    backend.apply(0.01, [TransientCommand(Axis.PITCH, 6.0, 0.3, 0.4, 0.25)])
    fake.calls.clear()
    backend.close()
    backend.close()
    teardown = ["unacquire", "release_device", "close"]
    zeroing = ["ff_command", *["set_parameters"] * 4]
    assert fake.names() == [*zeroing, *["release_effect"] * 6, *teardown]
    assert fake.calls[0] == STOP_ALL and released_ids(fake) == [0, 1, 2, 3, 4, 5]


def test_close_releases_device_even_when_all_off_fails() -> None:
    fake, backend = fresh()
    backend.apply(0.0, steady_tick())
    fake.fail["ff_command"] = di.DIERR_INVALIDPARAM
    with pytest.raises(di.DInputError):
        backend.close()
    assert (fake.count("release_effect"), fake.count("release_device")) == (4, 1)
    assert fake.closed


def test_apply_after_close_is_ignored(caplog: pytest.LogCaptureFixture) -> None:
    fake, backend = fresh()
    backend.apply(0.0, steady_tick())
    backend.close()
    fake.calls.clear()
    with caplog.at_level(logging.WARNING):
        backend.apply(0.02, [*steady_tick(), AllOffCommand()])
    backend.all_off()
    backend.close()
    assert fake.calls == []
    assert "already closed" in caplog.text


def test_loss_on_first_poll_still_tears_down() -> None:
    fake = FakeDirectInput(ab9())
    base = open_joystick(fake)
    backend = DInputHapticBackend(base, 1.0, axis_map=STANDARD_AXES)
    fake.devices[0].attached = False
    fake.calls.clear()
    result = run_loop(
        [make_engine("littlebird-miniguns")],
        base_source(base),
        backend,
        rate_hz=100,
        watchdog_s=0.25,
        clock=TickClock(0.005),
        sleep=lambda s: None,
        max_ticks=5,
    )
    assert (result.stopped_by, result.ticks) == ("device_lost", 0)
    names = fake.names()
    assert names[0] == "poll_state" and STOP_ALL in fake.calls
    assert names.index("ff_command") < names.index("release_device") and fake.closed
