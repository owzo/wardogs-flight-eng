"""DirectInput held effects: in-place updates, the restart latch, the pool."""

import logging
from dataclasses import replace

import pytest
from dinput_support import FakeDirectInput, ab9

from wardogs_flight_eng.engine.commands import Axis, PulseCommand, SpringCommand
from wardogs_flight_eng.inputs import dinput_api as di
from wardogs_flight_eng.inputs.dinput_api import DiEffect, DInputError
from wardogs_flight_eng.inputs.protocol import DeviceLostError
from wardogs_flight_eng.outputs.dinput_channel import (
    POOL_SIZE,
    DInputChannel,
    DInputPool,
    ForceFailure,
)
from wardogs_flight_eng.outputs.dinput_effects import (
    pulse_effect,
    silenced,
    spring_effect,
)
from wardogs_flight_eng.outputs.dinput_persistent import EffectKey, HeldEffects
from wardogs_flight_eng.outputs.haptic_axes import HapticAxis, HapticAxisMap

AXES = HapticAxisMap(HapticAxis(1, 1.0), HapticAxis(0, 1.0))
LENGTH_S = 1.0
PITCH: EffectKey = ("spring", Axis.PITCH)
ROLL: EffectKey = ("spring", Axis.ROLL)
E_INVALIDARG = -2147024809


def _spring(axis: Axis = Axis.PITCH, center: float = 0.0) -> DiEffect:
    return spring_effect(AXES, SpringCommand(axis, center, 0.5, 0.0), 1_000_000)


def _held() -> tuple[FakeDirectInput, HeldEffects]:
    fake = FakeDirectInput(ab9())
    return fake, HeldEffects(DInputChannel(fake, fake.devices[0]), LENGTH_S)


def _played(held: HeldEffects, t: float, key: EffectKey, effect: DiEffect) -> None:
    """``play`` as the backend calls it: only when ``due``."""
    if held.due(t, key, effect):
        held.play(t, key, effect)


def test_new_key_creates_then_starts() -> None:
    fake, held = _held()
    held.play(0.0, PITCH, _spring())
    assert fake.names() == ["create_effect", "start"]
    assert held.effect_ids == [0]
    assert held.restarted(PITCH)


def test_same_effect_within_half_length_makes_no_call() -> None:
    fake, held = _held()
    held.play(0.0, PITCH, _spring())
    for n in range(1, 50):
        _played(held, n / 100, PITCH, _spring())
    assert fake.names() == ["create_effect", "start"]


def test_changed_effect_updates_in_place_without_start() -> None:
    fake, held = _held()
    held.play(0.0, PITCH, _spring())
    _played(held, 0.1, PITCH, _spring(center=0.3))
    assert fake.names() == ["create_effect", "start", "set_parameters"]
    assert fake.args("set_parameters")[0][2] is True
    assert fake.effects[0] == _spring(center=0.3)
    assert not held.restarted(PITCH)


def test_refused_in_place_update_latches_a_restart(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake, held = _held()
    fake.norestart_unsupported = True
    held.play(0.0, PITCH, _spring())
    with caplog.at_level(logging.INFO):
        _played(held, 0.1, PITCH, _spring(center=0.3))
        first = [args[2] for args in fake.args("set_parameters")]
        assert held.restarted(PITCH)
        _played(held, 0.2, PITCH, _spring(center=0.4))
        _played(held, 0.3, ROLL, _spring(Axis.ROLL))
        _played(held, 0.4, ROLL, _spring(Axis.ROLL, center=0.2))
    assert first == [True, False]
    later = [args[2] for args in fake.args("set_parameters")][2:]
    assert later == [False, False]
    assert held.restart_latched == {"spring": True}
    notes = [r for r in caplog.records if "cannot update a playing" in r.message]
    assert len(notes) == 1
    assert notes[0].levelno == logging.INFO
    assert notes[0].getMessage().startswith("spring: ")


def test_restart_resets_the_half_life_timer() -> None:
    fake, held = _held()
    fake.norestart_unsupported = True
    held.play(0.0, PITCH, _spring())
    _played(held, 0.4, PITCH, _spring(center=0.3))  # restarted at 0.4
    _played(held, 0.8, PITCH, _spring(center=0.3))
    assert fake.count("start") == 1
    _played(held, 0.91, PITCH, _spring(center=0.3))
    assert fake.count("start") == 2


def test_other_set_parameters_failures_raise() -> None:
    fake, held = _held()
    held.play(0.0, PITCH, _spring())
    fake.fail["set_parameters"] = E_INVALIDARG
    with pytest.raises(DInputError):
        held.play(0.1, PITCH, _spring(center=0.3))
    assert held.restart_latched == {}
    assert held.due(0.2, PITCH, _spring(center=0.3))


def test_effect_playing_is_tolerated_only_for_an_in_place_update() -> None:
    fake = FakeDirectInput(ab9())
    channel = DInputChannel(fake, fake.devices[0])
    effect_id = channel.create(_spring())
    fake.fail["set_parameters"] = di.DIERR_EFFECTPLAYING
    status = channel.update(effect_id, _spring(), norestart=True)
    assert status == di.DIERR_EFFECTPLAYING
    with pytest.raises(DInputError):
        channel.update(effect_id, _spring(), norestart=False)


def test_rerun_starts_after_half_the_length() -> None:
    fake, held = _held()
    held.play(0.0, PITCH, _spring())
    _played(held, 0.5, PITCH, _spring())
    assert fake.count("start") == 1
    _played(held, 0.51, PITCH, _spring())
    assert fake.names() == ["create_effect", "start", "start"]
    assert held.restarted(PITCH)


def test_silence_updates_every_held_effect_and_marks_it_due() -> None:
    fake, held = _held()
    held.play(0.0, PITCH, _spring(center=0.2))
    held.play(0.0, ROLL, _spring(Axis.ROLL))
    failures: list[ForceFailure] = []
    held.silence(failures)
    assert failures == []
    assert fake.effects == {
        0: silenced(_spring(center=0.2)),
        1: silenced(_spring(Axis.ROLL)),
    }
    assert held.due(0.01, PITCH, silenced(_spring(center=0.2)))
    _played(held, 0.01, PITCH, silenced(_spring(center=0.2)))
    assert fake.names()[-1] == "start"


def test_silence_records_a_lost_device_and_tries_the_rest() -> None:
    fake, held = _held()
    held.play(0.0, PITCH, _spring())
    held.play(0.0, ROLL, _spring(Axis.ROLL))
    fake.devices[0].attached = False
    failures: list[ForceFailure] = []
    held.silence(failures)
    assert [type(f) for f in failures] == [DeviceLostError, DeviceLostError]
    assert fake.count("set_parameters") == 2


def test_stop_all_and_release_go_through_the_device() -> None:
    fake = FakeDirectInput(ab9())
    channel = DInputChannel(fake, fake.devices[0])
    effect_id = channel.create(_spring())
    channel.start(effect_id)
    channel.stop_all()
    assert fake.playing == set()
    assert fake.args("ff_command") == [(di.DISFFC_STOPALL,)]
    channel.release(effect_id)
    assert fake.effects == {}
    fake.fail["ff_command"] = di.DIERR_UNPLUGGED
    with pytest.raises(DeviceLostError):
        channel.stop_all()


def test_pool_reuses_finished_slots_and_stops_the_oldest() -> None:
    fake = FakeDirectInput(ab9())
    pool = DInputPool(DInputChannel(fake, fake.devices[0]))
    pulse = pulse_effect(AXES, PulseCommand(Axis.PITCH, 0.5, 0.1))
    for n in range(POOL_SIZE + 1):
        pool.play(n / 100, replace(pulse, gain=9000 + n), 0.1)
    assert fake.count("create_effect") == POOL_SIZE
    assert fake.args("stop") == [(0,)]
    assert fake.args("set_parameters")[-1][0] == 0
    pool.play(1.0, pulse, 0.1)  # every slot has finished: the first is reused
    assert fake.count("create_effect") == POOL_SIZE
    assert fake.count("stop") == 1
    assert pool.effect_ids == [0, 1, 2, 3]
