"""``make-preset``: writes a Moza Cockpit preset and prints what changed."""

import json
import os
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


def _make(
    template: Path, out: Path, division: str = "A", profile: Path = LAKOTA
) -> list[str]:
    return [
        "make-preset",
        "--profile",
        str(profile),
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


def test_make_preset_reads_a_bom_prefixed_template(tmp_path: Path) -> None:
    template = tmp_path / "bom.preset"
    template.write_bytes(b"\xef\xbb\xbf" + FIXTURE.read_bytes())
    out = tmp_path / "new.preset"
    result = invoke(_make(template, out))
    assert result.code == 0, result.output
    assert json.loads(out.read_text(encoding="utf-8"))["device_params"]


def test_make_preset_refuses_to_overwrite_its_template(tmp_path: Path) -> None:
    template = tmp_path / "mine.preset"
    template.write_bytes(FIXTURE.read_bytes())
    result = invoke(_make(template, template))
    assert result.code == 1
    assert f"--out {template}: refuses to overwrite the template it reads" in (
        result.output
    )
    assert template.read_bytes() == FIXTURE.read_bytes()


def test_make_preset_leaves_no_staging_file(tmp_path: Path) -> None:
    out = tmp_path / "new.preset"
    assert invoke(_make(FIXTURE, out)).code == 0
    assert out.exists() and not list(tmp_path.glob("*.tmp"))


def test_make_preset_refuses_to_overwrite_its_profile(tmp_path: Path) -> None:
    profile = tmp_path / "mine.json"
    profile.write_bytes(LAKOTA.read_bytes())
    result = invoke(_make(FIXTURE, profile, profile=profile))
    assert result.code == 1
    assert f"--out {profile}: refuses to overwrite the profile it reads" in (
        result.output
    )
    assert profile.read_bytes() == LAKOTA.read_bytes()


def test_make_preset_stages_under_a_unique_name(tmp_path: Path) -> None:
    out = tmp_path / "new.preset"
    stale = tmp_path / "new.preset.tmp"
    stale.write_text("another writer's staging file", encoding="utf-8")
    assert invoke(_make(FIXTURE, out)).code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["device_params"]
    assert stale.read_text(encoding="utf-8") == "another writer's staging file"
    assert list(tmp_path.glob("*.tmp")) == [stale]


def test_make_preset_failed_replace_leaves_no_staging_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(source: object, target: object) -> None:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(os, "replace", refuse)
    out = tmp_path / "new.preset"
    result = invoke(_make(FIXTURE, out))
    assert result.code == 1
    assert f"cannot write preset {out}: Access is denied" in result.output
    assert not out.exists() and not list(tmp_path.glob("*.tmp"))
