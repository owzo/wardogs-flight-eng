"""Engine and control-frame builders shared by the synthesiser tests."""

from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.commands import (
    Axis,
    Command,
    FrictionCommand,
    SineCommand,
)
from wardogs_flight_eng.engine.frame import Button, ControlFrame
from wardogs_flight_eng.engine.profile import PROFILES_DIR, load_profile
from wardogs_flight_eng.engine.synth import FlightEngine

PROFILES = PROFILES_DIR


def engine_for(name: str) -> FlightEngine:
    return FlightEngine(load_profile(PROFILES / f"{name}.json"), load_constants())


def frame(
    pitch: float = 0,
    roll: float = 0,
    collective: float = 0,
    pedals: float = 0,
    *held: Button,
) -> ControlFrame:
    return ControlFrame(pitch, roll, collective, pedals, frozenset(held))


def pitch_friction(cmds: list[Command]) -> float:
    return next(
        c.coefficient
        for c in cmds
        if isinstance(c, FrictionCommand) and c.axis is Axis.PITCH
    )


def sine_magnitude(cmds: list[Command]) -> float:
    return next(c.magnitude for c in cmds if isinstance(c, SineCommand))
