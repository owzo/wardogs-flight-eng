"""Load the packaged game constants, failing loudly on malformed input."""

import json
from importlib import resources
from pathlib import Path
from typing import Any

from wardogs_flight_eng.constants.model import (
    Airframe,
    GameConstants,
    InputFacts,
    Provenance,
    Shake,
    Weapon,
)

_DATA_FILE = "wardogs_heli_constants.json"


class ConstantsError(ValueError):
    """The constants file is unreadable, malformed, or missing a key."""


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _airframe(key: str, raw: dict[str, Any]) -> Airframe:
    return Airframe(
        key=key,
        plugin=str(raw["plugin"]),
        mass_kg=float(raw["mass_kg"]),
        main_rotor_rpm=float(raw["main_rotor_rpm"]),
        rpm_source=str(raw["rpm_source"]),
        spool_down_rpm_per_s=_optional_float(raw["spool_down_rpm_per_s"]),
    )


def _weapon(key: str, raw: dict[str, Any]) -> Weapon:
    rounds = raw["rounds_per_reload"]
    shake = raw["shake"]
    return Weapon(
        key=key,
        asset=str(raw["asset"]),
        rounds_per_minute=float(raw["rounds_per_minute"]),
        windup_s=float(raw["windup_s"]),
        reload_s=float(raw["reload_s"]),
        reload_breakdown=tuple(float(x) for x in raw["reload_breakdown"]),
        shake_multiplier=_optional_float(raw["shake_multiplier"]),
        shake=None if shake is None else str(shake),
        recoil_pattern=tuple(
            (float(yaw), float(pitch)) for yaw, pitch in raw["recoil_pattern"]
        ),
        rounds_per_reload=None if rounds is None else int(rounds),
    )


def _shake(key: str, raw: dict[str, Any]) -> Shake:
    return Shake(
        key=key,
        asset=str(raw["asset"]),
        frequency_hz=float(raw["frequency_hz"]),
        duration_s=float(raw["duration_s"]),
        blend_in_s=float(raw["blend_in_s"]),
        blend_out_s=float(raw["blend_out_s"]),
    )


def _build(raw: dict[str, Any]) -> GameConstants:
    prov = raw["provenance"]
    facts = raw["input"]
    shakes = {k: _shake(k, v) for k, v in raw["shakes"].items()}
    weapons = {k: _weapon(k, v) for k, v in raw["weapons"].items()}
    for weapon in weapons.values():
        if weapon.shake is not None and weapon.shake not in shakes:
            raise ConstantsError(
                f"weapon {weapon.key!r} references unknown shake {weapon.shake!r}"
            )
    return GameConstants(
        provenance=Provenance(
            build_id=str(prov["build_id"]),
            extracted_at=str(prov["extracted_at"]),
            mappings=str(prov["mappings"]),
        ),
        airframes={k: _airframe(k, v) for k, v in raw["airframes"].items()},
        weapons=weapons,
        shakes=shakes,
        input=InputFacts(
            pedal_heading_hold_threshold=float(facts["pedal_heading_hold_threshold"]),
            hotas_deadzone_default=float(facts["hotas_deadzone_default"]),
        ),
    )


def _read_text(path: Path | None) -> str:
    if path is not None:
        return path.read_text(encoding="utf-8")
    resource = resources.files("wardogs_flight_eng") / "data" / _DATA_FILE
    return resource.read_text(encoding="utf-8")


def load_constants(path: Path | None = None) -> GameConstants:
    """Load constants from ``path``, or from the packaged data file."""
    try:
        return _build(json.loads(_read_text(path)))
    except ConstantsError:
        raise
    except KeyError as err:
        raise ConstantsError(f"missing key {err.args[0]!r} in constants") from err
    except (OSError, TypeError, ValueError) as err:
        raise ConstantsError(f"malformed constants: {err}") from err
