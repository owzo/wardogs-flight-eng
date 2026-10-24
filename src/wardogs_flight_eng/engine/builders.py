"""Builders: a profile and the game constants into the engine's models.

``FlightEngine`` builds its rotor, weapon and airspeed estimator here, and
rebuilds the weapon here on a profile handoff.
"""

import logging

from wardogs_flight_eng.constants.model import Airframe, GameConstants, Weapon
from wardogs_flight_eng.engine.flight_state import InputEstimator, StateEstimator
from wardogs_flight_eng.engine.profile import Profile
from wardogs_flight_eng.engine.rotor import RotorModel
from wardogs_flight_eng.engine.weapon import WeaponModel

DEFAULT_SPOOL_DOWN_RPM_PER_S = 850.0
"""Littlebird game spool-down (``DA_ROT_03_Engine``); not other airframes' data."""

log = logging.getLogger(__name__)

_PULSE_DUTY = 0.5
"""Recoil pulse length as a fraction of the interval between rounds."""


def build_rotor(profile: Profile, airframe: Airframe) -> RotorModel:
    """The profile's rotor buzz at the airframe's operating RPM."""
    return RotorModel(
        operating_rpm=airframe.main_rotor_rpm,
        spool_up_s=profile.rotor.spool_up_s,
        spool_down_rpm_per_s=_spool_down(profile, airframe),
        base_amplitude=profile.rotor.base_amplitude,
        deflection_factor=profile.rotor.deflection_factor,
        airspeed_factor=profile.rotor.airspeed_factor,
    )


def build_weapon(
    profile: Profile, constants: GameConstants
) -> tuple[WeaponModel | None, float]:
    """The pilot weapon in its idle state and its recoil pulse length in seconds.

    A profile without a pilot weapon gives ``(None, 0.0)``.
    """
    if profile.pilot_weapon is None:
        return None, 0.0
    weapon = constants.weapons[profile.pilot_weapon]
    pulse_s = _PULSE_DUTY * 60.0 / weapon.rounds_per_minute
    return _weapon_model(weapon, profile, constants), pulse_s


def build_estimator(profile: Profile) -> StateEstimator:
    """The airspeed estimator the profile's ``estimator`` block names.

    ``kind`` has the single value ``"input"`` today, so it always builds an
    ``InputEstimator``.
    """
    settings = profile.estimator
    return InputEstimator(settings.forward_threshold, settings.tau_s)


def _spool_down(profile: Profile, airframe: Airframe) -> float:
    """Profile override, else the airframe's constant, else the placeholder."""
    for rate in (profile.rotor.spool_down_rpm_per_s, airframe.spool_down_rpm_per_s):
        if rate is not None:
            return rate
    log.info(
        "%s: spool-down rate unknown; using %g rpm/s, the Littlebird's game "
        "value, not this airframe's",
        profile.airframe,
        DEFAULT_SPOOL_DOWN_RPM_PER_S,
    )
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
