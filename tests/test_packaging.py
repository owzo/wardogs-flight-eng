"""Packaging: the data files ship in the package and the build spec names them."""

import json
from importlib import resources
from pathlib import Path

from wardogs_flight_eng.engine.profile import load_profile

PROFILE_NAMES = ("havoc", "lakota", "littlebird-miniguns", "littlebird-rockets")
SPEC = Path(__file__).resolve().parents[1] / "packaging" / "wardogs-flight-eng.spec"


def test_package_data_included() -> None:
    root = resources.files("wardogs_flight_eng")
    constants = root.joinpath("data", "wardogs_heli_constants.json")
    assert json.loads(constants.read_text(encoding="utf-8"))["provenance"]
    for name in PROFILE_NAMES:
        profile = root.joinpath("profiles", f"{name}.json")
        assert profile.is_file(), name
        assert load_profile(Path(str(profile))).name == name


def test_pyinstaller_spec_parses_and_names_the_data_directories() -> None:
    text = SPEC.read_text(encoding="utf-8")
    compile(text, str(SPEC), "exec")
    assert "wardogs_flight_eng/data" in text
    assert "wardogs_flight_eng/profiles" in text
    assert "wardogs-flight-eng" in text
    assert "sdl2dll" in text
