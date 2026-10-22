"""SimulatedDevice and the scripted Scenario."""

import json
from pathlib import Path
from typing import Any

import pytest

from wardogs_flight_eng.inputs.composite import CompositeInput
from wardogs_flight_eng.inputs.protocol import InputConfigError
from wardogs_flight_eng.inputs.simulated import Scenario, SimulatedDevice

SCENARIOS = Path(__file__).parent / "scenarios"


def test_scenario_drives_devices_over_time() -> None:
    s = Scenario.load(SCENARIOS / "takeoff-trim-fire.json")
    s.apply_until(2.0)
    assert s.devices["coll"].axes[0] == pytest.approx(0.2)
    s.apply_until(5.05)
    assert s.devices["grip"].buttons[0] is True  # trim lock down at 5.0
    s.apply_until(6.0)
    assert s.devices["grip"].buttons[0] is False  # released at 5.1


def test_scenario_metadata_and_composite_dry_run() -> None:
    s = Scenario.load(SCENARIOS / "takeoff-trim-fire.json")
    assert s.rate_hz == 100
    assert s.duration_s == 12.0
    composite = CompositeInput(s.device_map, dict(s.devices))
    s.apply_until(4.0)
    frame = composite.read()
    assert frame.pitch == pytest.approx(0.3)
    assert frame.collective == pytest.approx(0.6)


def test_steps_are_applied_once_and_state_persists() -> None:
    s = Scenario.load(SCENARIOS / "takeoff-trim-fire.json")
    s.apply_until(5.05)
    s.devices["grip"].buttons[0] = False  # external change must not be re-applied
    s.apply_until(5.06)
    assert s.devices["grip"].buttons[0] is False


def test_simulated_device_defaults() -> None:
    d = SimulatedDevice("pedals", axis_count=1, button_count=2)
    assert (d.name, d.guid, d.alive) == ("pedals", "sim-pedals", True)
    assert d.axes == [0.0]
    assert d.buttons == [False, False]
    d.poll()
    assert d.axis(0) == 0.0
    assert d.button(1) is False


def _scenario_json(steps: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "rate_hz": 100,
            "device_map": {
                "devices": {},
                "axes": {},
                "buttons": {},
                "calibration": {},
            },
            "devices": {},
            "steps": steps,
        }
    )


def test_scenario_rejects_unsorted_steps(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(_scenario_json([{"t": 2, "set": {}}, {"t": 1, "set": {}}]))
    with pytest.raises(InputConfigError, match="sorted"):
        Scenario.load(path)


def test_scenario_rejects_unknown_target(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(_scenario_json([{"t": 0, "set": {"stick.axis0": 0.1}}]))
    with pytest.raises(InputConfigError, match="stick.axis0"):
        Scenario.load(path)
