import json
from pathlib import Path

import pytest
from profile_support import PROFILES, raw_profile

from wardogs_flight_eng.cli_profiles import write_calibration
from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.engine.frame import Button
from wardogs_flight_eng.engine.profile import (
    MIGRATION_HINT_FIELDS,
    Calibration,
    DeviceMap,
    Profile,
    ProfileError,
    load_profile,
)

FIXTURES = Path(__file__).parent / "fixtures"


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
    raw = raw_profile("havoc")
    raw["feel"]["spring_coeficient"] = 0.4
    bad = tmp_path / "p.json"
    bad.write_text(json.dumps(raw))
    with pytest.raises(ProfileError, match="feel.spring_coeficient"):
        load_profile(bad)


def test_out_of_range_coefficient_rejected(tmp_path: Path) -> None:
    raw = raw_profile("havoc")
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
    raw = raw_profile("havoc")
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
    raw = raw_profile("lakota")
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


@pytest.mark.parametrize("field", sorted(MIGRATION_HINT_FIELDS))
def test_missing_0_2_0_field_gets_the_migration_hint(field: str) -> None:
    raw = raw_profile("lakota")
    *parents, leaf = field.split(".")
    section = raw
    for part in parents:
        section = section[part]
    del section[leaf]
    with pytest.raises(ProfileError, match=f"{field}: .*predates 0.2.0"):
        Profile.from_document(raw)


def test_missing_pre_existing_field_gets_no_migration_hint() -> None:
    raw = raw_profile("lakota")
    del raw["rotor"]["base_amplitude"]
    with pytest.raises(ProfileError) as err:
        Profile.from_document(raw)
    assert "predates 0.2.0" not in str(err.value)
    assert "base_amplitude" in str(err.value)


def test_calibrate_rewrite_path_reports_the_migration_hint(tmp_path: Path) -> None:
    old = tmp_path / "old.json"
    old.write_bytes((FIXTURES / "littlebird-v0.1.0.json").read_bytes())
    with pytest.raises(ProfileError, match="predates 0.2.0"):
        write_calibration(old, Calibration())
    assert old.read_bytes() == (FIXTURES / "littlebird-v0.1.0.json").read_bytes()
