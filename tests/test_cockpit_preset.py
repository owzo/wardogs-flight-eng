"""Moza Cockpit preset rewriting: division A and B keys, metadata, refusals."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from profile_support import PROFILES, raw_profile

from wardogs_flight_eng.cockpit_preset import PresetError, rewrite_preset
from wardogs_flight_eng.engine.profile import Profile, load_profile

FIXTURES = Path(__file__).parent / "fixtures"


def _template(name: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return document


@pytest.fixture
def template() -> dict[str, Any]:
    return _template("cockpit-template.preset")


@pytest.fixture
def template_unbound() -> dict[str, Any]:
    return _template("cockpit-template-unbound.preset")


@pytest.fixture
def lakota() -> Profile:
    return load_profile(PROFILES / "lakota.json")


@pytest.fixture
def littlebird() -> Profile:
    return load_profile(PROFILES / "littlebird-miniguns.json")


@pytest.fixture
def zero() -> Profile:
    """Lakota with spring 0 (and friction 0, which may be at most spring / 4)."""
    raw = raw_profile("lakota")
    raw["feel"]["spring_coefficient"] = 0.0
    raw["feel"]["friction"] = 0.0
    return Profile.from_document(raw)


def test_division_a_rewrites_exactly_the_seven_keys_and_keeps_order(
    template: dict[str, Any], lakota: Profile
) -> None:
    doc, changes = rewrite_preset(
        template, "A", lakota, name=None, now=1, new_uuid="{u}"
    )
    assert {
        c.key: c.new for c in changes if c.key.startswith(("bacic", "hardware"))
    } == {
        "bacic_spring": 0,
        "bacic_damper": 0,
        "bacic_friction": 0,
        "bacic_inertia": 0,
        "bacic_start_force_enble": 0,
        "hardware_balancing_enable": 0,
        "bacic_gameForceFeedback": 100,
    }
    assert list(doc) == list(template)
    assert list(doc["device_params"]) == list(template["device_params"])
    assert doc["device_params"]["bacic_overall_strength"] == 70
    assert doc["name"] == "Synthetic + Flight Eng A"
    assert doc["uuid"] == "{u}" and doc["date"] == "1"


def test_changes_are_in_document_order_with_old_and_new(
    template: dict[str, Any], lakota: Profile
) -> None:
    _, changes = rewrite_preset(template, "A", lakota, name=None, now=1, new_uuid="{u}")
    assert [c.key for c in changes] == [
        "date",
        "bacic_damper",
        "bacic_friction",
        "bacic_gameForceFeedback",
        "bacic_inertia",
        "bacic_spring",
        "bacic_start_force_enble",
        "hardware_balancing_enable",
        "name",
        "uuid",
    ]
    assert (changes[0].old, changes[0].new) == ("1700000000", "1")
    assert (changes[5].old, changes[5].new) == (40, 0)


def test_rewritten_values_keep_integer_type(
    template: dict[str, Any], lakota: Profile
) -> None:
    doc, _ = rewrite_preset(template, "A", lakota, name=None, now=1, new_uuid="{u}")
    assert all(
        type(doc["device_params"][k]) is int
        for k in ("bacic_spring", "bacic_gameForceFeedback")
    )


def test_the_template_is_not_modified(
    template: dict[str, Any], lakota: Profile
) -> None:
    before = copy.deepcopy(template)
    rewrite_preset(template, "A", lakota, name="Mine", now=1, new_uuid="{u}")
    assert template == before


def test_name_overrides_the_default(template: dict[str, Any], lakota: Profile) -> None:
    doc, _ = rewrite_preset(template, "A", lakota, name="Mine", now=1, new_uuid="{u}")
    assert doc["name"] == "Mine"


def test_division_b_requires_force_trim_with_zero_spring(
    template: dict[str, Any], lakota: Profile, littlebird: Profile, zero: Profile
) -> None:
    with pytest.raises(PresetError, match=r"spring_coefficient 0 .*'lakota'.*0\.5"):
        rewrite_preset(template, "B", lakota, name=None, now=1, new_uuid="{u}")
    with pytest.raises(PresetError, match="force_trim profile; .* is unboosted"):
        rewrite_preset(template, "B", littlebird, name=None, now=1, new_uuid="{u}")
    doc, changes = rewrite_preset(template, "B", zero, name=None, now=1, new_uuid="{u}")
    params = doc["device_params"]
    assert params["bacic_spring"] == template["device_params"]["bacic_spring"]
    assert params["bacic_start_force_enble"] == 1
    assert params["hardware_balancing_enable"] == 1
    bound = (params["hardware_balancing_trim"], params["hardware_balancing_recenter"])
    assert bound == (3, 17)
    assert {c.key for c in changes if c.key.startswith("bacic")} == {
        "bacic_damper",
        "bacic_friction",
        "bacic_inertia",
        "bacic_gameForceFeedback",
    }
    assert doc["name"] == "Synthetic + Flight Eng B"


def test_division_b_refuses_unbound_trim_buttons(
    template_unbound: dict[str, Any], zero: Profile
) -> None:
    with pytest.raises(
        PresetError,
        match="hardware_balancing_trim.*hardware_balancing_recenter.*bind the buttons",
    ):
        rewrite_preset(template_unbound, "B", zero, name=None, now=1, new_uuid="{u}")


def test_division_b_refuses_a_missing_trim_button(
    template: dict[str, Any], zero: Profile
) -> None:
    del template["device_params"]["hardware_balancing_recenter"]
    with pytest.raises(PresetError, match="bind the buttons in Moza Cockpit"):
        rewrite_preset(template, "B", zero, name=None, now=1, new_uuid="{u}")


def test_division_a_ignores_unbound_trim_buttons(
    template_unbound: dict[str, Any], lakota: Profile
) -> None:
    doc, _ = rewrite_preset(
        template_unbound, "A", lakota, name=None, now=1, new_uuid="{u}"
    )
    assert doc["device_params"]["hardware_balancing_enable"] == 0


def test_missing_required_key_names_it(
    template: dict[str, Any], lakota: Profile
) -> None:
    del template["device_params"]["bacic_damper"]
    with pytest.raises(PresetError, match="bacic_damper"):
        rewrite_preset(template, "A", lakota, name=None, now=1, new_uuid="{u}")


@pytest.mark.parametrize("params", [None, [], "x", 3])
def test_non_object_device_params_is_refused(
    template: dict[str, Any], lakota: Profile, params: object
) -> None:
    template["device_params"] = params
    with pytest.raises(PresetError, match="device_params"):
        rewrite_preset(template, "A", lakota, name=None, now=1, new_uuid="{u}")


def test_a_template_without_a_name_needs_one_given(
    template: dict[str, Any], lakota: Profile
) -> None:
    del template["name"]
    with pytest.raises(PresetError, match="name"):
        rewrite_preset(template, "A", lakota, name=None, now=1, new_uuid="{u}")
    doc, _ = rewrite_preset(template, "A", lakota, name="Given", now=1, new_uuid="{u}")
    assert doc["name"] == "Given"
