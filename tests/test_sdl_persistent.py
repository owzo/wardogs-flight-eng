"""Persistent effects: upload only on change, re-run at half their length."""

from dataclasses import replace

from sdl_haptic_support import effect_calls, open_backend, per_effect, steady_tick
from sdl_support import FakeSdl, stick

from wardogs_flight_eng.engine.commands import Axis, Command, SineCommand, SpringCommand
from wardogs_flight_eng.outputs.sdl_effects import advance_phase

TICKS = 100  # at 0.01 s: 0.00 .. 0.99 s, against a 1.0 s persistent length


def _created(fake: FakeSdl) -> list[int]:
    return [effect_id for effect_id, _ in effect_calls(fake, "SDL_HapticNewEffect")]


def _stiffer_pitch(commands: list[Command]) -> list[Command]:
    return [
        replace(c, center=0.3)
        if isinstance(c, SpringCommand) and c.axis == Axis.PITCH
        else c
        for c in commands
    ]


def test_identical_ticks_upload_once_and_rerun_only_at_half_length() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake, length_s=1.0)
    for n in range(TICKS):
        backend.apply(n / 100, steady_tick())
    created = _created(fake)
    assert len(created) == 4
    updates, runs = (
        per_effect(fake, "SDL_HapticUpdateEffect"),
        per_effect(fake, "SDL_HapticRunEffect"),
    )
    assert all(updates.get(effect_id, 0) <= 1 for effect_id in created)
    # a spring re-runs as uploaded; a sine re-uploads once to carry its phase
    assert [updates.get(effect_id, 0) for effect_id in created] == [0, 0, 1, 1]
    assert all(2 <= runs[effect_id] <= 3 for effect_id in created)  # 0 s, 0.51 s


def test_changed_spring_centre_updates_and_runs_exactly_once() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake, length_s=1.0)
    for n in range(50):
        backend.apply(n / 100, steady_tick())
    pitch_spring = _created(fake)[0]
    before = len(fake.calls)
    backend.apply(0.5, _stiffer_pitch(steady_tick()))  # tick 50
    assert fake.calls[before:] == [
        ("SDL_HapticUpdateEffect", (pitch_spring, fake.effects[pitch_spring])),
        ("SDL_HapticRunEffect", (pitch_spring, 1)),
    ]
    assert fake.effects[pitch_spring].condition.center == (0, 9830, 0)
    for n in range(51, TICKS):
        backend.apply(n / 100, _stiffer_pitch(steady_tick()))
    assert per_effect(fake, "SDL_HapticUpdateEffect")[pitch_spring] == 1


def test_all_off_zeroes_and_the_next_tick_reuploads_and_runs() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake)
    for n in range(10):
        backend.apply(n / 100, steady_tick())
    backend.all_off()
    silenced = [effect for _, effect in effect_calls(fake, "SDL_HapticUpdateEffect")]
    assert len(silenced) == 4
    assert all(e.condition.right_coeff == (0, 0, 0) for e in silenced[:2])
    assert all(e.periodic.magnitude == 0 for e in silenced[2:])
    before = len(fake.calls)
    backend.apply(0.1, steady_tick())
    names = [name for name, _ in fake.calls[before:]]
    assert names.count("SDL_HapticUpdateEffect") == 4
    assert names.count("SDL_HapticRunEffect") == 4
    created = _created(fake)
    assert fake.effects[created[0]].condition.right_coeff == (0, 11468, 0)
    assert fake.effects[created[2]].periodic.magnitude == 13107


def test_sine_restarts_from_the_phase_its_waveform_reached() -> None:
    fake = FakeSdl(stick())
    backend = open_backend(fake, length_s=1.0)
    sine = SineCommand(Axis.PITCH, 5.5067, 0.4)  # 182 ms period
    for n in range(52):  # 0.51 s is the first tick past half the length
        backend.apply(n / 100, [sine])
    rerun = [
        effect.periodic.phase
        for _, effect in effect_calls(fake, "SDL_HapticUpdateEffect")
    ]
    assert rerun == [advance_phase(0, 0.51, 182)]
    backend.apply(0.6, [replace(sine, magnitude=0.5)])  # changed: restart now
    phases = [e.periodic.phase for _, e in effect_calls(fake, "SDL_HapticUpdateEffect")]
    assert phases[-1] == advance_phase(advance_phase(0, 0.51, 182), 0.6 - 0.51, 182)
    assert phases[-1] == advance_phase(0, 0.6, 182)  # one continuous waveform
