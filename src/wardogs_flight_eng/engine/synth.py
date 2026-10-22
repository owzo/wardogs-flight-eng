"""Flight engine: one control frame per tick in, force-feedback commands out.

Composes the trim spring, rotor buzz and pilot-weapon recoil for one profile.
Each tick: detect button taps (rising edges against the previous frame), honour
the all-off latch and the stalled-tick watchdog, dispatch taps, advance the
models, then assemble springs, sines and any recoil for the tick.
"""

import math

from wardogs_flight_eng.constants.model import Airframe, GameConstants, Weapon
from wardogs_flight_eng.engine.commands import (
    AllOffCommand,
    Axis,
    Command,
    PulseCommand,
    SineCommand,
    SpringCommand,
    TransientCommand,
)
from wardogs_flight_eng.engine.frame import Button, ControlFrame
from wardogs_flight_eng.engine.profile import Profile
from wardogs_flight_eng.engine.rotor import RotorModel
from wardogs_flight_eng.engine.trim import TrimState
from wardogs_flight_eng.engine.weapon import WeaponModel

DEFAULT_SPOOL_DOWN_RPM_PER_S = 850.0
"""Game spool-down (``DA_ROT_03_Engine``) used when nothing better is known."""

_PULSE_DUTY = 0.5
"""Recoil pulse length as a fraction of the interval between rounds."""


def _spool_down(profile: Profile, airframe: Airframe) -> float:
    """Profile override, else the airframe's constant, else the game default."""
    for rate in (profile.rotor.spool_down_rpm_per_s, airframe.spool_down_rpm_per_s):
        if rate is not None:
            return rate
    return DEFAULT_SPOOL_DOWN_RPM_PER_S


def _weapon_model(
    weapon: Weapon, profile: Profile, constants: GameConstants
) -> WeaponModel:
    """``weapon`` with the profile's recoil and its shake resolved."""
    shake = None if weapon.shake is None else constants.shakes[weapon.shake]
    return WeaponModel(
        weapon,
        amplitude=profile.recoil.amplitude,
        rocket_kick=profile.recoil.rocket_kick,
        shake=shake,
    )


class FlightEngine:
    """Per-profile force-feedback synthesiser; pure and deterministic."""

    def __init__(self, profile: Profile, constants: GameConstants) -> None:
        """Build the models for ``profile``; ``ProfileError`` if it names unknowns."""
        profile.validate_against(constants)
        airframe = constants.airframes[profile.airframe]
        self._profile = profile
        self._trim = TrimState(profile.feel.trim_slew_s)
        self._rotor = RotorModel(
            operating_rpm=airframe.main_rotor_rpm,
            spool_up_s=profile.rotor.spool_up_s,
            spool_down_rpm_per_s=_spool_down(profile, airframe),
            base_amplitude=profile.rotor.base_amplitude,
            deflection_factor=profile.rotor.deflection_factor,
        )
        self._weapon: WeaponModel | None = None
        self._pulse_s = 0.0
        if profile.pilot_weapon is not None:
            weapon = constants.weapons[profile.pilot_weapon]
            self._weapon = _weapon_model(weapon, profile, constants)
            self._pulse_s = _PULSE_DUTY * 60.0 / weapon.rounds_per_minute
        self._previous_held: frozenset[Button] = frozenset()
        self._all_off = False

    @property
    def profile(self) -> Profile:
        """The profile this engine was built for."""
        return self._profile

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

    def step(self, dt: float, frame: ControlFrame) -> list[Command]:
        """Advance ``dt`` seconds and return this tick's commands.

        A latched ALL_OFF or a stalled tick (``dt > safety.watchdog_s``)
        returns exactly ``[AllOffCommand()]`` and advances no model.
        """
        taps = frame.held - self._previous_held
        self._previous_held = frame.held
        if Button.ALL_OFF in taps:
            self._all_off = not self._all_off
        if self._all_off or dt > self._profile.safety.watchdog_s:
            return [AllOffCommand()]
        self._dispatch(taps, frame)
        self._trim.step(dt)
        self._rotor.step(dt)
        return [*self._springs(), *self._buzz(frame), *self._recoil(dt, frame, taps)]

    def _dispatch(self, taps: frozenset[Button], frame: ControlFrame) -> None:
        """Apply the trim and rotor taps of this tick."""
        if Button.TRIM_LOCK in taps:
            self._trim.lock(frame.pitch, frame.roll)
        if Button.TRIM_RESET in taps:
            self._trim.reset()
        if Button.ROTOR_TOGGLE in taps:
            self._rotor.toggle()

    def _springs(self) -> list[Command]:
        """Pitch and roll centring springs about the trim centre."""
        feel = self._profile.feel
        roll_coefficient = feel.spring_coefficient * feel.roll_scale
        return [
            SpringCommand(
                Axis.PITCH,
                self._trim.center_pitch,
                feel.spring_coefficient,
                feel.deadband,
            ),
            SpringCommand(
                Axis.ROLL, self._trim.center_roll, roll_coefficient, feel.deadband
            ),
        ]

    def _buzz(self, frame: ControlFrame) -> list[Command]:
        """1/rev rotor vibration on both axes, boosted by cyclic deflection."""
        deflection = math.hypot(
            frame.pitch - self._trim.center_pitch,
            frame.roll - self._trim.center_roll,
        )
        magnitude = self._rotor.amplitude(frame.collective, min(deflection, 1.0))
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
