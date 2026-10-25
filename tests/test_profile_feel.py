"""Profile feel modes, condition gains and the estimator block."""

from pathlib import Path
from typing import Any

import pytest
from profile_support import PROFILES, raw_profile

from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.profile import (
    Estimator,
    Profile,
    ProfileError,
    load_profile,
)


def test_shipped_profiles_carry_the_decided_feel() -> None:
    lb = load_profile(PROFILES / "littlebird-miniguns.json")
    feel = lb.feel
    assert (
        feel.mode,
        feel.spring_coefficient,
        feel.friction,
        feel.clamp_friction,
        feel.damper,
        feel.inertia,
        lb.rotor.airspeed_factor,
    ) == ("unboosted", 0.12, 0.02, 0.5, 0.15, 0.05, 0.6)
    assert lb.estimator == Estimator(kind="input", forward_threshold=0.15, tau_s=4.0)
    havoc = load_profile(PROFILES / "havoc.json")
    assert havoc.feel.mode == "force_trim" and havoc.feel.clamp_friction is None
    assert {"friction", "damper", "inertia", "airspeed_factor"} <= set(havoc.taste)


def test_shipped_littlebird_rockets_and_lakota_carry_the_decided_feel() -> None:
    rockets = load_profile(PROFILES / "littlebird-rockets.json")
    assert (
        rockets.feel.mode,
        rockets.feel.spring_coefficient,
        rockets.feel.friction,
        rockets.feel.clamp_friction,
        rockets.feel.damper,
        rockets.feel.inertia,
        rockets.rotor.airspeed_factor,
    ) == ("unboosted", 0.12, 0.02, 0.5, 0.15, 0.05, 0.6)
    lakota = load_profile(PROFILES / "lakota.json")
    assert (
        lakota.feel.mode,
        lakota.feel.spring_coefficient,
        lakota.feel.friction,
        lakota.feel.clamp_friction,
        lakota.feel.damper,
        lakota.feel.inertia,
        lakota.rotor.airspeed_factor,
    ) == ("force_trim", 0.5, 0.1, None, 0.25, 0.08, 0.15)
    assert lakota.estimator == Estimator(
        kind="input", forward_threshold=0.15, tau_s=4.0
    )


def test_friction_exactly_a_quarter_of_the_spring_is_accepted() -> None:
    raw = raw_profile("lakota")
    raw["feel"]["friction"] = raw["feel"]["spring_coefficient"] / 4
    assert Profile.from_document(raw).feel.friction == 0.125


def test_v0_1_0_profile_fails_with_migration_hint() -> None:
    with pytest.raises(ProfileError, match="feel.mode.*predates 0.2.0.*calibrate"):
        load_profile(Path(__file__).parent / "fixtures" / "littlebird-v0.1.0.json")


@pytest.mark.parametrize(
    ("update", "needle"),
    [
        ({"mode": "force_trim", "clamp_friction": 0.4}, "clamp_friction is only valid"),
        ({"mode": "unboosted", "clamp_friction": None}, "clamp_friction is required"),
        ({"friction": 0.2}, "spring_coefficient / 4"),  # 0.2 > 0.5 / 4 on lakota
        (
            {"mode": "unboosted", "friction": 0.1, "clamp_friction": 0.05},
            r"clamp_friction 0\.05 must be >= feel\.friction 0\.1",
        ),
    ],
)
def test_feel_rules_are_enforced(update: dict[str, Any], needle: str) -> None:
    raw = raw_profile("lakota")
    raw["feel"].update(update)
    with pytest.raises(ProfileError, match=needle):
        Profile.from_document(raw)


def test_condition_gains_above_ceiling_are_profile_errors() -> None:
    raw = raw_profile("lakota")
    raw["feel"]["damper"] = 0.7
    with pytest.raises(ProfileError, match="feel.damper"):
        Profile.from_document(raw).validate_against(load_constants())


def test_clamp_friction_above_ceiling_is_a_profile_error() -> None:
    raw = raw_profile("littlebird-miniguns")
    raw["feel"]["clamp_friction"] = 0.7
    with pytest.raises(ProfileError, match=r"feel\.clamp_friction 0\.7 is above"):
        Profile.from_document(raw).validate_against(load_constants())


def test_estimator_threshold_below_one() -> None:
    raw = raw_profile("lakota")
    raw["estimator"]["forward_threshold"] = 1.0
    with pytest.raises(ProfileError, match="forward_threshold"):
        Profile.from_document(raw)
