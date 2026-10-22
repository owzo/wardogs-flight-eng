"""Game constants: values, provenance, sentinel rendering, malformed input."""

import dataclasses
import json
from pathlib import Path

import pytest

from wardogs_flight_eng.constants.loader import ConstantsError, load_constants
from wardogs_flight_eng.constants.model import UNKNOWN, describe

DATA_FILE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "wardogs_flight_eng"
    / "data"
    / "wardogs_heli_constants.json"
)
PATTERN = (
    (1.107, 2.406),
    (-0.308, 1.661),
    (-0.988, 0.876),
    (-0.548, 1.838),
    (0.504, 1.501),
    (-0.205, 2.853),
    (-1.093, 2.003),
)


def test_littlebird_one_per_rev() -> None:
    c = load_constants()
    assert c.airframes["littlebird"].one_per_rev_hz == pytest.approx(5.5067, abs=1e-3)
    assert c.airframes["lakota"].one_per_rev_hz == pytest.approx(4.1667, abs=1e-3)
    assert c.airframes["havoc"].one_per_rev_hz == pytest.approx(4.5)


def test_minigun_reload_is_summed_breakdown() -> None:
    w = load_constants().weapons["littlebird_miniguns"]
    assert w.reload_s == 6.25 and sum(w.reload_breakdown) == 6.25
    assert len(w.recoil_pattern) == 7 and w.recoil_pattern[0] == (1.107, 2.406)


def test_both_machine_guns_share_the_recoil_pattern() -> None:
    c = load_constants()
    assert c.weapons["littlebird_miniguns"].recoil_pattern == PATTERN
    assert c.weapons["havoc_mg"].recoil_pattern == PATTERN


def test_unknown_values_render_sentinel() -> None:
    w = load_constants().weapons["littlebird_rockets"]
    assert w.rounds_per_reload is None
    assert describe(w.rounds_per_reload) == "UNKNOWN - WARDOGS GAME VALUE REQUIRED"
    assert describe(None) == UNKNOWN
    assert describe(2.5) == "2.5"
    assert describe(7) == "7"


def test_unknown_airframe_values_stay_none() -> None:
    c = load_constants()
    assert c.airframes["littlebird"].spool_down_rpm_per_s == 850
    assert c.airframes["lakota"].spool_down_rpm_per_s is None
    assert c.airframes["havoc"].spool_down_rpm_per_s is None


def test_provenance_build_id() -> None:
    p = load_constants().provenance
    assert p.build_id == "25937608"
    assert p.extracted_at == "2026-10-22"
    assert p.mappings == "Wardogs20261015-new.usmap"


def test_rocket_shake_envelope() -> None:
    c = load_constants()
    shake_key = c.weapons["littlebird_rockets"].shake
    assert shake_key is not None
    s = c.shakes[shake_key]
    assert (s.frequency_hz, s.duration_s, s.blend_out_s) == (6, 0.4, 0.25)
    assert c.weapons["littlebird_miniguns"].shake is None


def test_weapon_shake_keys_resolve_to_shakes() -> None:
    c = load_constants()
    assert {w.shake for w in c.weapons.values()} == {
        None,
        "littlebird_heli_firing",
        "heli_firing",
    }
    for w in c.weapons.values():
        assert w.shake is None or w.shake in c.shakes
    assert set(c.shakes) == {
        "heli_firing",
        "littlebird_heli_firing",
        "havoc_mg_firing",
        "crash_first_person",
        "landed_first_person",
    }


def test_input_facts() -> None:
    i = load_constants().input
    assert (i.pedal_heading_hold_threshold, i.hotas_deadzone_default) == (0.05, 0.05)


def test_dataclasses_are_frozen() -> None:
    c = load_constants()
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.provenance.build_id = "0"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.airframes["lakota"].mass_kg = 1  # type: ignore[misc]


def test_explicit_path_loads_same_data(tmp_path: Path) -> None:
    default = load_constants()
    data = DATA_FILE
    copy = tmp_path / "c.json"
    copy.write_text(data.read_text(encoding="utf-8"), encoding="utf-8")
    assert load_constants(copy) == default


def test_missing_key_is_named_in_error(tmp_path: Path) -> None:
    raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    del raw["airframes"]["lakota"]["mass_kg"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ConstantsError, match="mass_kg"):
        load_constants(bad)


def test_non_json_is_constants_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConstantsError):
        load_constants(bad)


def test_constants_error_is_value_error() -> None:
    assert issubclass(ConstantsError, ValueError)
