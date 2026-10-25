"""``make-preset``: writes a Moza Cockpit preset and prints what changed."""

import json
from pathlib import Path

import pytest
from cli_support import invoke
from profile_support import PROFILES

from wardogs_flight_eng import cli

FIXTURE = Path(__file__).parent / "fixtures" / "cockpit-template.preset"
LAKOTA = PROFILES / "lakota.json"


@pytest.fixture(autouse=True)
def quiet_logging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ``setup_logging`` from installing handlers."""
    monkeypatch.setattr(cli, "setup_logging", lambda verbose: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))


def _make(template: Path, out: Path, division: str = "A") -> list[str]:
    return [
        "make-preset",
        "--profile",
        str(LAKOTA),
        "--template",
        str(template),
        "--division",
        division,
        "--out",
        str(out),
    ]


def test_make_preset_writes_the_file_and_prints_the_table(tmp_path: Path) -> None:
    out = tmp_path / "new.preset"
    result = invoke(_make(FIXTURE, out))
    assert result.code == 0
    assert out.exists() and "bacic_spring" in result.output
    assert str(out) in result.output
    assert "'lakota' (force_trim)" in result.output
    document = json.loads(out.read_text(encoding="utf-8"))
    assert document["device_params"]["bacic_spring"] == 0
    assert document["name"] == "Synthetic + Flight Eng A"
    assert document["uuid"].startswith("{") and document["uuid"].endswith("}")
    assert document["date"].isdigit()
    assert out.read_text(encoding="utf-8").endswith("}\n")
    assert out.read_bytes().startswith(b'{\n    "date"')


def test_make_preset_uses_the_given_name(tmp_path: Path) -> None:
    out = tmp_path / "new.preset"
    result = invoke([*_make(FIXTURE, out), "--name", "My Heli"])
    assert result.code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["name"] == "My Heli"


def test_make_preset_with_a_non_json_template_exits_1(tmp_path: Path) -> None:
    template = tmp_path / "broken.preset"
    template.write_text("{not json", encoding="utf-8")
    out = tmp_path / "new.preset"
    result = invoke(_make(template, out))
    assert result.code == 1
    assert str(template) in result.output and not out.exists()


def test_make_preset_with_a_non_object_template_exits_1(tmp_path: Path) -> None:
    template = tmp_path / "list.preset"
    template.write_text("[1, 2]", encoding="utf-8")
    result = invoke(_make(template, tmp_path / "new.preset"))
    assert result.code == 1 and str(template) in result.output


def test_make_preset_division_b_refusal_exits_1(tmp_path: Path) -> None:
    out = tmp_path / "new.preset"
    result = invoke(_make(FIXTURE, out, "B"))
    assert result.code == 1
    assert "spring_coefficient 0" in result.output and not out.exists()


def test_make_preset_rejects_an_unknown_division(tmp_path: Path) -> None:
    result = invoke(_make(FIXTURE, tmp_path / "new.preset", "C"))
    assert result.code == 1 and "invalid choice" in result.output
