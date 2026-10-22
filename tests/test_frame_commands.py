import pytest

from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Axis,
    PulseCommand,
    SineCommand,
    SpringCommand,
    TransientCommand,
)
from wardogs_flight_eng.engine.frame import Button, ControlFrame


def test_frame_rejects_out_of_range_collective() -> None:
    with pytest.raises(ValueError):
        ControlFrame(0, 0, 1.2, 0, frozenset())


@pytest.mark.parametrize(
    "pitch, roll, collective, pedals",
    [
        (1.1, 0, 0.5, 0),
        (-1.1, 0, 0.5, 0),
        (0, 1.1, 0.5, 0),
        (0, -1.1, 0.5, 0),
        (0, 0, -0.1, 0),
        (0, 0, 0.5, 1.1),
        (0, 0, 0.5, -1.1),
    ],
)
def test_frame_rejects_each_out_of_range_axis(
    pitch: float, roll: float, collective: float, pedals: float
) -> None:
    with pytest.raises(ValueError):
        ControlFrame(pitch, roll, collective, pedals, frozenset())


def test_frame_accepts_range_boundaries_and_is_hashable() -> None:
    frame = ControlFrame(-1, 1, 0, -1, frozenset({Button.FIRE}))
    assert frame == ControlFrame(-1, 1, 0, -1, frozenset({Button.FIRE}))
    assert hash(frame)


def test_commands_are_hashable_value_objects() -> None:
    a = SpringCommand(Axis.PITCH, 0.0, 0.5, 0.02)
    assert a == SpringCommand(Axis.PITCH, 0.0, 0.5, 0.02) and hash(a)


def test_all_command_types_hash_and_all_off_values_are_equal() -> None:
    commands = {
        SineCommand(Axis.ROLL, 12.0, 0.3),
        PulseCommand(Axis.PITCH, -0.5, 0.05),
        TransientCommand(Axis.ROLL, 30.0, 0.4, 0.2, 0.1),
        AllOffCommand(),
        AllOffCommand(),
    }
    assert len(commands) == 4
    assert AllOffCommand() == AllOffCommand()
