"""``ScenarioRecorder``: raw device snapshots become a replayable scenario."""

import json
from pathlib import Path

from cli_support import BOUND_MAP

from wardogs_flight_eng.engine.device_map import DeviceMap
from wardogs_flight_eng.inputs.simulated import Scenario
from wardogs_flight_eng.runtime.dry_run import replay_ticks
from wardogs_flight_eng.runtime.recorder import DeviceSnapshot, ScenarioRecorder

DEVICE_MAP = DeviceMap.model_validate(BOUND_MAP)


def _snap(*axes: float, buttons: tuple[bool, ...] = ()) -> DeviceSnapshot:
    return DeviceSnapshot(tuple(axes), buttons)


def test_recorder_writes_initial_changes_and_closing_steps() -> None:
    r = ScenarioRecorder(100.0, 0.005)
    r.begin(0.0, {"stick": DeviceSnapshot((0.0, 0.1), (False,))})
    r.observe(0.01, {"stick": DeviceSnapshot((0.0, 0.1), (False,))})
    r.observe(0.02, {"stick": DeviceSnapshot((0.003, 0.1), (False,))})
    r.observe(0.03, {"stick": DeviceSnapshot((0.2, 0.1), (True,))})
    doc = r.finish(0.05, DEVICE_MAP)
    assert doc["steps"] == [
        {
            "t": 0.0,
            "set": {"stick.axis0": 0.0, "stick.axis1": 0.1, "stick.button0": False},
        },
        {"t": 0.03, "set": {"stick.axis0": 0.2, "stick.button0": True}},
        {"t": 0.05, "set": {}},
    ]
    assert doc["devices"] == {"stick": {"axes": 2, "buttons": 1}}
    assert doc["rate_hz"] == 100.0 and r.step_count == 3


def test_small_moves_accumulate_against_the_last_written_value() -> None:
    r = ScenarioRecorder(100.0, 0.005)
    r.begin(0.0, {"base": _snap(0.0)})
    r.observe(0.01, {"base": _snap(0.003)})
    r.observe(0.02, {"base": _snap(0.006)})
    r.observe(0.03, {"base": _snap(0.009)})
    steps = r.finish(0.04, DEVICE_MAP)["steps"]
    assert steps[1] == {"t": 0.02, "set": {"base.axis0": 0.006}}
    assert len(steps) == 3


def test_axis_values_are_rounded_to_three_decimals() -> None:
    r = ScenarioRecorder(50.0, 0.005)
    r.begin(0.0, {"base": _snap(0.123456, -0.98765)})
    first = r.finish(0.0, DEVICE_MAP)["steps"][0]["set"]
    assert first == {"base.axis0": 0.123, "base.axis1": -0.988}


def test_document_carries_the_device_map_verbatim() -> None:
    r = ScenarioRecorder(100.0, 0.005)
    r.begin(0.0, {"base": _snap(0.0, buttons=(False,)), "pedals": _snap(0.0)})
    doc = r.finish(0.0, DEVICE_MAP)
    assert doc["device_map"] == DEVICE_MAP.model_dump(mode="json")
    assert doc["devices"] == {
        "base": {"axes": 1, "buttons": 1},
        "pedals": {"axes": 1, "buttons": 0},
    }


def test_recorded_document_round_trips_through_scenario_load(tmp_path: Path) -> None:
    r = ScenarioRecorder(100.0, 0.005)
    r.begin(
        0.0, {"base": _snap(0.0, 0.0, -1.0, buttons=(False,)), "pedals": _snap(0.0)}
    )
    r.observe(
        0.5, {"base": _snap(0.4, 0.0, -1.0, buttons=(True,)), "pedals": _snap(0.0)}
    )
    path = tmp_path / "flight.json"
    path.write_text(json.dumps(r.finish(1.0, DEVICE_MAP), indent=2), encoding="utf-8")
    scenario = Scenario.load(path)
    assert scenario.rate_hz == 100.0 and scenario.duration_s == 1.0
    assert scenario.device_map == DEVICE_MAP
    scenario.apply_until(0.5)
    assert scenario.devices["base"].axes[0] == 0.4
    assert scenario.devices["base"].buttons == [True]


def test_a_step_replays_on_its_own_tick_at_120_hz(tmp_path: Path) -> None:
    r = ScenarioRecorder(120.0, 0.005)
    r.begin(0.0, {"base": _snap(0.0)})
    r.observe(2 / 120, {"base": _snap(0.5)})
    path = tmp_path / "flight.json"
    path.write_text(json.dumps(r.finish(7 / 120, DEVICE_MAP)), encoding="utf-8")
    scenario = Scenario.load(path)
    scenario.apply_until(1 / 120)
    assert scenario.devices["base"].axes[0] == 0.0
    scenario.apply_until(2 / 120)
    assert scenario.devices["base"].axes[0] == 0.5
    assert replay_ticks(scenario) == 7


def test_a_closing_step_never_precedes_the_last_step() -> None:
    r = ScenarioRecorder(100.0, 0.005)
    r.begin(0.0, {"base": _snap(0.0)})
    r.observe(0.05, {"base": _snap(0.5)})
    assert r.finish(0.03, DEVICE_MAP)["steps"][-1] == {"t": 0.05, "set": {}}


def test_zero_min_change_records_any_change_but_skips_unchanged_axes() -> None:
    r = ScenarioRecorder(100.0, 0.0)
    r.begin(0.0, {"base": _snap(0.0, 0.5)})
    r.observe(0.01, {"base": _snap(0.001, 0.5)})
    r.observe(0.02, {"base": _snap(0.001, 0.5)})
    steps = r.finish(0.03, DEVICE_MAP)["steps"]
    assert steps[1:] == [
        {"t": 0.01, "set": {"base.axis0": 0.001}},
        {"t": 0.03, "set": {}},
    ]
