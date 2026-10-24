"""Flight engine: one control frame per tick in, force-feedback commands out.

Composes the feel conditions, rotor buzz and pilot-weapon recoil for one
profile. Each tick: detect button taps (rising edges against the previous
frame), honour the all-off latch and the stalled-tick watchdog, dispatch taps,
advance the models and the flight-state estimate, then assemble the
conditions, sines and any recoil for the tick.
"""

import math

from wardogs_flight_eng.constants.model import GameConstants
from wardogs_flight_eng.engine.builders import (
    DEFAULT_SPOOL_DOWN_RPM_PER_S,
    build_estimator,
    build_rotor,
    build_weapon,
)
from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Axis,
    Command,
    PulseCommand,
    SineCommand,
    TransientCommand,
)
from wardogs_flight_eng.engine.feel import FeelModel
from wardogs_flight_eng.engine.flight_state import FlightState, StateEstimator
from wardogs_flight_eng.engine.frame import Button, ControlFrame
from wardogs_flight_eng.engine.profile import Profile

__all__ = ["DEFAULT_SPOOL_DOWN_RPM_PER_S", "FlightEngine"]

_AT_REST = FlightState(airspeed=0.0, collective=0.0, deflection=0.0)


class FlightEngine:
    """Per-profile force-feedback synthesiser; pure and deterministic."""

    def __init__(
        self,
        profile: Profile,
        constants: GameConstants,
        estimator: StateEstimator | None = None,
    ) -> None:
        """Build the models for ``profile``; ``ProfileError`` if it names unknowns.

        ``estimator`` defaults to the one the profile's ``estimator`` block names.
        """
        profile.validate_against(constants)
        self._profile = profile
        self._constants = constants
        self._feel = FeelModel(profile.feel)
        self._rotor = build_rotor(profile, constants.airframes[profile.airframe])
        self._weapon, self._pulse_s = build_weapon(profile, constants)
        self._estimator = build_estimator(profile) if estimator is None else estimator
        self._state = _AT_REST
        self._previous_held: frozenset[Button] = frozenset()
        self._all_off = False

    @property
    def profile(self) -> Profile:
        """The profile this engine was built for."""
        return self._profile

    @property
    def state(self) -> FlightState:
        """The flight state of the last tick (at rest before the first)."""
        return self._state

    @property
    def all_off(self) -> bool:
        """``True`` while the ALL_OFF latch holds every force off."""
        return self._all_off

    @all_off.setter
    def all_off(self, value: bool) -> None:
        """Set the latch, e.g. carried over from the engine handing off control."""
        self._all_off = value

    def prime_buttons(self, held: frozenset[Button]) -> None:
        """Treat ``held`` as last tick's buttons, so still-held ones are not taps.

        Used when this engine takes over mid-flight: without it a button held
        across a profile switch (ALL_OFF above all) would read as a fresh tap.
        """
        self._previous_held = held

    def take_over(self, outgoing: "FlightEngine") -> None:
        """Take control from ``outgoing`` on a profile switch.

        The feel restarts centred and free, the airspeed estimate at rest and
        the weapon idle; the rotor adopts the outgoing spool fraction and
        running flag; the ALL_OFF latch and the held buttons carry over.
        """
        self._feel.restart()
        self._estimator.restart()
        self._state = _AT_REST
        self._rotor.take_over(outgoing._rotor.spool_fraction, outgoing._rotor.running)
        self._weapon, self._pulse_s = build_weapon(self._profile, self._constants)
        self._all_off = outgoing.all_off
        self.prime_buttons(outgoing._previous_held)

    def step(self, dt: float, frame: ControlFrame) -> list[Command]:
        """Advance ``dt`` seconds and return this tick's commands.

        A latched ALL_OFF, or a ``dt`` outside ``0..safety.watchdog_s`` (a
        stalled tick, a negative gap, NaN or infinity: the gate fails closed),
        returns exactly ``[AllOffCommand()]`` and advances no model.
        """
        taps = frame.held - self._previous_held
        self._previous_held = frame.held
        if Button.ALL_OFF in taps:
            self._all_off = not self._all_off
        if self._all_off or not (0.0 <= dt <= self._profile.safety.watchdog_s):
            return [AllOffCommand()]
        self._dispatch(taps, frame)
        self._feel.step(dt)
        self._rotor.step(dt)
        self._state = self._estimator.step(dt, frame, self._deflection(frame))
        recoil = self._recoil(dt, frame, taps)
        return [*self._feel.conditions(), *self._buzz(), *recoil]

    def _dispatch(self, taps: frozenset[Button], frame: ControlFrame) -> None:
        """Apply the trim and rotor taps of this tick."""
        if Button.TRIM_LOCK in taps:
            self._feel.lock(frame.pitch, frame.roll)
        if Button.TRIM_RESET in taps:
            self._feel.reset()
        if Button.ROTOR_TOGGLE in taps:
            self._rotor.toggle()

    def _deflection(self, frame: ControlFrame) -> float:
        """Cyclic distance from the feel centre, capped at 1."""
        return min(
            1.0,
            math.hypot(
                frame.pitch - self._feel.center_pitch,
                frame.roll - self._feel.center_roll,
            ),
        )

    def _buzz(self) -> list[Command]:
        """1/rev rotor vibration on both axes from this tick's flight state."""
        state = self._state
        magnitude = self._rotor.amplitude(
            state.collective, state.deflection, state.airspeed
        )
        frequency = self._rotor.frequency_hz
        return [
            SineCommand(Axis.PITCH, frequency, magnitude),
            SineCommand(Axis.ROLL, frequency, magnitude),
        ]

    def _recoil(
        self, dt: float, frame: ControlFrame, taps: frozenset[Button]
    ) -> list[Command]:
        """Pulses (and shake transients) for each round the weapon fired."""
        if self._weapon is None:
            return []
        rounds = self._weapon.step(dt, Button.FIRE in frame.held, Button.RELOAD in taps)
        commands: list[Command] = []
        for roll, pitch in rounds:
            commands += [
                PulseCommand(Axis.PITCH, pitch, self._pulse_s),
                PulseCommand(Axis.ROLL, roll, self._pulse_s),
            ]
            commands += self._shake()
        return commands

    def _shake(self) -> list[Command]:
        """One shake transient per axis for a round, if the weapon has a shake."""
        shake = None if self._weapon is None else self._weapon.shake
        if shake is None:
            return []
        magnitude = self._profile.recoil.shake_amplitude
        return [
            TransientCommand(
                axis,
                shake.frequency_hz,
                magnitude,
                shake.duration_s,
                shake.blend_out_s,
            )
            for axis in (Axis.PITCH, Axis.ROLL)
        ]
