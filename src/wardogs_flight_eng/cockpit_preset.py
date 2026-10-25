"""Rewrite a Moza Cockpit ``.preset`` for one division of labour with Flight Eng.

Pure: it takes the parsed template and returns a new document plus the list of
changes; reading and writing files is ``cli_preset``'s job. Only the
division's ``device_params`` keys and the ``name``, ``uuid`` and ``date``
metadata change; every other key keeps its value and its position.

**A**: Flight Eng owns spring, friction, damper, inertia and trim, so Cockpit's
are zeroed and its hardware balancing (trim) is off. **B**: Cockpit owns the
spring and hardware trim; its spring and trim buttons stay as the user set
them, and the Flight Eng profile must be ``force_trim`` with spring 0.
"""

import copy
from dataclasses import dataclass
from typing import Any, Final, Literal

from wardogs_flight_eng.engine.profile import Profile

Division = Literal["A", "B"]

TRIM_KEYS: Final = ("hardware_balancing_trim", "hardware_balancing_recenter")

DIVISION_A: Final[dict[str, int]] = {
    "bacic_spring": 0,
    "bacic_damper": 0,
    "bacic_friction": 0,
    "bacic_inertia": 0,
    "bacic_start_force_enble": 0,
    "hardware_balancing_enable": 0,
    "bacic_gameForceFeedback": 100,
}
DIVISION_B: Final[dict[str, int]] = {
    "bacic_damper": 0,
    "bacic_friction": 0,
    "bacic_inertia": 0,
    "hardware_balancing_enable": 1,
    "bacic_gameForceFeedback": 100,
}
REQUIRED_KEYS: Final = (*DIVISION_A, *TRIM_KEYS)
"""``device_params`` keys every template must have, whichever the division."""

_DIVISIONS: Final[dict[str, dict[str, int]]] = {"A": DIVISION_A, "B": DIVISION_B}


class PresetError(ValueError):
    """The template or the profile cannot make a preset for the division."""


@dataclass(frozen=True, slots=True)
class Change:
    """One key the rewrite changed (``old`` is ``None`` if it was absent)."""

    key: str
    old: object
    new: object


def rewrite_preset(
    document: dict[str, Any],
    division: Division,
    profile: Profile,
    *,
    name: str | None,
    now: int,
    new_uuid: str,
) -> tuple[dict[str, Any], list[Change]]:
    """Return a copy of ``document`` rewritten for ``division`` and its changes.

    ``name`` replaces the default ``"<template name> + Flight Eng <division>"``;
    ``now`` (Unix seconds) becomes ``date`` as a string. The changes are in
    document order, ``device_params`` keys where that object sits. Raises
    ``PresetError`` naming the key or rule the template or profile breaks.
    """
    params = document.get("device_params")
    if not isinstance(params, dict):
        raise PresetError("template device_params must be a JSON object")
    if division == "B":
        _check_division_b(params, profile)
    for key in REQUIRED_KEYS:
        if key not in params:
            raise PresetError(f"template device_params has no {key!r}")
    rewritten = copy.deepcopy(document)
    rewritten["device_params"].update(_DIVISIONS[division])
    rewritten.update(
        date=str(now),
        name=_default_name(document, division) if name is None else name,
        uuid=new_uuid,
    )
    return rewritten, _changes(document, rewritten)


def _check_division_b(params: dict[str, Any], profile: Profile) -> None:
    feel = profile.feel
    if feel.mode != "force_trim":
        raise PresetError(
            f"division B needs a force_trim profile; {profile.name!r} is {feel.mode}"
        )
    if feel.spring_coefficient != 0:
        raise PresetError(
            f"division B needs feel.spring_coefficient 0 in profile "
            f"{profile.name!r} (it is {feel.spring_coefficient}): "
            "Moza Cockpit owns the spring"
        )
    if not all(params.get(key) for key in TRIM_KEYS):
        raise PresetError(
            "division B needs hardware_balancing_trim and "
            "hardware_balancing_recenter bound in the template (both are 0 or "
            "missing): bind the buttons in Moza Cockpit and export again"
        )


def _default_name(document: dict[str, Any], division: Division) -> str:
    template_name = document.get("name")
    if not isinstance(template_name, str):
        raise PresetError("template has no string 'name': give the preset a name")
    return f"{template_name} + Flight Eng {division}"


def _changes(before: dict[str, Any], after: dict[str, Any]) -> list[Change]:
    """Every key of ``after`` whose value or type differs from ``before``."""
    changes: list[Change] = []
    for key, new in after.items():
        if key == "device_params":
            changes.extend(_changes(before[key], new))
            continue
        old = before.get(key)
        if key not in before or old != new or type(old) is not type(new):
            changes.append(Change(key, old, new))
    return changes
