import json
from pathlib import Path
from typing import Any

import pytest

from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.frame import Button
from wardogs_flight_eng.engine.profile import (
    PROFILES_DIR,
    Calibration,
    DeviceMap,
    Estimator,
    Profile,
    ProfileError,
    load_profile,
)

PROFILES = PROFILES_DIR


def _raw(name: str) -> dict[str, Any]:
    raw: dict[str, Any] = json.loads(
        (PROFILES / f"{name}.json").read_text(encoding="utf-8")
    )
    return raw


@pytest.mark.parametrize(
    "name", ["littlebird-miniguns", "littlebird-rockets", "lakota", "havoc"]
)
def test_shipped_profiles_load_and_validate(name: str) -> None:
    p = load_profile(PROFILES / f"{name}.json")
    p.validate_against(load_constants())
    assert "spring_coefficient" in p.taste


def test_bad_field_named_in_error(tmp_path: Path) -> None:
    bad = tmp_path / "p.json"
    bad.write_text(
        '{"name": "x", "airframe": "littlebird", '
        '"feel": {"spring_coefficient": "soft"}}'
    )
    with pytest.raises(ProfileError, match="spring_coefficient"):
        load_profile(bad)


def test_unknown_weapon_rejected() -> None:
    p = load_profile(PROFILES / "lakota.json").model_copy(
        update={"pilot_weapon": "laser"}
    )
    with pytest.raises(ProfileError, match="laser"):
        p.validate_against(load_constants())


def test_unknown_airframe_rejected() -> None:
    p = load_profile(PROFILES / "havoc.json").model_copy(
        update={"airframe": "blackhawk"}
    )
    with pytest.raises(ProfileError, match="blackhawk"):
        p.validate_against(load_constants())


def test_unreadable_json_names_the_file(tmp_path: Path) -> None:
    bad = tmp_path / "p.json"
    bad.write_text("{not json")
    with pytest.raises(ProfileError, match=r"p\.json"):
        load_profile(bad)


def test_missing_file_is_profile_error(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match=r"missing\.json"):
        load_profile(tmp_path / "missing.json")


def test_misspelt_key_rejected_by_name(tmp_path: Path) -> None:
    raw = _raw("havoc")
    raw["feel"]["spring_coeficient"] = 0.4
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps(raw))
    with pytest.raises(ProfileError, match="feel.spring_coeficient"):
        load_profile(bad)


def test_out_of_range_coefficient_rejected(tmp_path: Path) -> None:
    raw = _raw("havoc")
    raw["feel"]["spring_coefficient"] = 1.5
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps(raw))
    with pytest.raises(ProfileError, match="feel.spring_coefficient"):
        load_profile(bad)


def test_shipped_values_match_owner_taste() -> None:
    lakota = load_profile(PROFILES / "lakota.json")
    assert lakota.pilot_weapon == "lakota_rockets"
    assert lakota.verify_in_game == ["pilot_weapon"]
    assert lakota.feel.spring_coefficient == 0.5 and lakota.feel.roll_scale == 0.5
    assert lakota.feel.deadband == 0.02 and lakota.feel.trim_slew_s == 0.3
    assert lakota.rotor.base_amplitude == 0.3 and lakota.recoil.amplitude == 0.6
    assert lakota.rotor.spool_up_s == 3.0 and lakota.rotor.deflection_factor == 0.5
    assert lakota.rotor.spool_down_rpm_per_s is None
    assert lakota.recoil.rocket_kick == (0.0, -1.0)
    assert lakota.recoil.shake_amplitude == 0.3
    assert lakota.safety.force_ceiling == 0.6 and lakota.safety.watchdog_s == 0.25
    havoc = load_profile(PROFILES / "havoc.json")
    assert havoc.pilot_weapon is None and havoc.recoil.amplitude == 0
    assert havoc.feel.spring_coefficient == 0.6


def test_device_map_parses_bindings() -> None:
    dm = DeviceMap.model_validate(
        {
            "devices": {"grip": {"guid": "abc", "product": "AB9"}},
            "axes": {"pitch": {"device": "grip", "axis": 1, "invert": True}},
            "buttons": {"fire": {"device": "grip", "button": 0}},
            "calibration": {},
        }
    )
    assert dm.axes["pitch"].invert is True
    assert dm.buttons[Button.FIRE].button == 0
    assert dm.calibration == Calibration()


@pytest.mark.parametrize(
    ("section", "key", "literal"),
    [
        ("safety", "watchdog_s", "Infinity"),
        ("feel", "spring_coefficient", "NaN"),
        ("feel", "trim_slew_s", "NaN"),
        ("rotor", "spool_down_rpm_per_s", "Infinity"),
        ("rotor", "spool_up_s", "Infinity"),
    ],
)
def test_non_finite_floats_rejected_by_name(
    tmp_path: Path, section: str, key: str, literal: str
) -> None:
    raw = _raw("havoc")
    raw[section][key] = float(literal.lower().replace("infinity", "inf"))
    text = json.dumps(raw)  # json writes the bare Infinity / NaN literals
    assert literal in text
    bad = tmp_path / "p.json"
    bad.write_text(text)
    with pytest.raises(ProfileError, match=f"{section}.{key}"):
        load_profile(bad)


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("feel", "spring_coefficient"),
        ("rotor", "base_amplitude"),
        ("recoil", "amplitude"),
        ("recoil", "shake_amplitude"),
        ("feel", "damper"),
        ("feel", "inertia"),
    ],
)
def test_gain_above_force_ceiling_rejected_by_name(
    tmp_path: Path, section: str, key: str
) -> None:
    raw = _raw("lakota")
    raw["safety"]["force_ceiling"] = 0.65
    raw[section][key] = 0.7
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps(raw))
    profile = load_profile(bad)
    with pytest.raises(ProfileError, match=rf"{section}\.{key} 0\.7 is above"):
        profile.validate_against(load_constants())


def test_gain_equal_to_force_ceiling_is_allowed() -> None:
    havoc = load_profile(PROFILES / "havoc.json")
    assert havoc.feel.spring_coefficient == havoc.safety.force_ceiling
    havoc.validate_against(load_constants())


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
    raw = _raw("lakota")
    raw["feel"].update(update)
    with pytest.raises(ProfileError, match=needle):
        Profile.from_document(raw)


def test_condition_gains_above_ceiling_are_profile_errors() -> None:
    raw = _raw("lakota")
    raw["feel"]["damper"] = 0.7
    with pytest.raises(ProfileError, match="feel.damper"):
        Profile.from_document(raw).validate_against(load_constants())


def test_clamp_friction_above_ceiling_is_a_profile_error() -> None:
    raw = _raw("littlebird-miniguns")
    raw["feel"]["clamp_friction"] = 0.7
    with pytest.raises(ProfileError, match=r"feel\.clamp_friction 0\.7 is above"):
        Profile.from_document(raw).validate_against(load_constants())


def test_estimator_threshold_below_one() -> None:
    raw = _raw("lakota")
    raw["estimator"]["forward_threshold"] = 1.0
    with pytest.raises(ProfileError, match="forward_threshold"):
        Profile.from_document(raw)
