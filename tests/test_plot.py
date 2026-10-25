"""The self-contained SVG force plot."""

import json
from pathlib import Path
from typing import Any

from dry_run_support import SCENARIOS, profile

from wardogs_flight_eng.constants.loader import load_constants
from wardogs_flight_eng.inputs.simulated import Scenario
from wardogs_flight_eng.runtime.dry_run import dry_run
from wardogs_flight_eng.runtime.plot import write_plot_html


def _write_log(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _small_log(tmp_path: Path) -> Path:
    rows: list[dict[str, Any]] = []
    for n in range(100):
        t = n / 100
        for axis in ("pitch", "roll"):
            rows.append(
                {"t": t, "kind": "spring", "axis": axis, "center": t / 2,
                 "coefficient": 0.5, "deadband": 0.0}
            )  # fmt: skip
            rows.append({"t": t, "kind": "sine", "axis": axis, "frequency_hz": 20.0,
                         "magnitude": 0.2})  # fmt: skip
    rows.append({"t": 0.3, "kind": "pulse", "axis": "pitch", "magnitude": 0.4,
                 "duration_s": 0.02})  # fmt: skip
    rows.append({"t": 0.4, "kind": "pulse", "axis": "roll", "magnitude": -0.4,
                 "duration_s": 0.02})  # fmt: skip
    rows.append({"t": 0.5, "kind": "transient", "axis": "pitch", "frequency_hz": 30.0,
                 "magnitude": 0.3, "duration_s": 0.1, "blend_out_s": 0.05})  # fmt: skip
    rows.append({"t": 0.9, "kind": "all_off"})
    return _write_log(tmp_path / "forces.jsonl", rows)


def test_plot_has_four_rows(tmp_path: Path) -> None:
    scenario = Scenario.load(SCENARIOS / "takeoff-trim-fire.json")
    _, plot = dry_run(
        profile("littlebird-miniguns"), load_constants(), scenario, tmp_path
    )
    html = plot.read_text(encoding="utf-8")
    assert html.count('class="title"') == 4
    for title in ("pitch", "roll", "pitch gains", "roll gains"):
        assert f">{title}<" in html


def test_plot_draws_every_event_and_the_all_off_marker(tmp_path: Path) -> None:
    out = tmp_path / "plot.html"
    write_plot_html(_small_log(tmp_path), out)
    html = out.read_text(encoding="utf-8")
    assert html.count('class="pulse up"') == 1
    assert html.count('class="pulse down"') == 1
    assert html.count('class="transient"') == 1
    assert html.count('class="all-off"') == 1
    assert html.count('class="spring-line"') == 2
    assert html.count('class="sine-line"') == 2


def test_plot_is_self_contained(tmp_path: Path) -> None:
    out = tmp_path / "plot.html"
    write_plot_html(_small_log(tmp_path), out)
    html = out.read_text(encoding="utf-8")
    assert "<script" not in html
    assert "http://" not in html.replace("http://www.w3.org/2000/svg", "")
    assert "https://" not in html
    assert "<style>" in html and "<svg" in html


def test_plot_labels_the_time_axis_in_seconds(tmp_path: Path) -> None:
    out = tmp_path / "plot.html"
    write_plot_html(_small_log(tmp_path), out)
    html = out.read_text(encoding="utf-8")
    assert "time (s)" in html
    assert 'class="tick-label"' in html


def test_plot_of_an_empty_log_still_has_every_row(tmp_path: Path) -> None:
    log = _write_log(tmp_path / "empty.jsonl", [])
    out = tmp_path / "plot.html"
    write_plot_html(log, out)
    html = out.read_text(encoding="utf-8")
    assert html.count('class="axis-row"') == 2
    assert html.count('class="gain-row"') == 2


def test_plot_draws_gain_lines_for_each_condition(tmp_path: Path) -> None:
    log = _write_log(
        tmp_path / "f.jsonl",
        [
            {"t": 0.0, "kind": "friction", "axis": "pitch", "coefficient": 0.02},
            {"t": 0.3, "kind": "friction", "axis": "pitch", "coefficient": 0.5},
            {"t": 0.0, "kind": "damper", "axis": "roll", "coefficient": 0.15},
            {"t": 0.0, "kind": "inertia", "axis": "roll", "coefficient": 0.05},
            {
                "t": 0.0,
                "kind": "spring",
                "axis": "pitch",
                "center": 0.0,
                "coefficient": 0.12,
                "deadband": 0.02,
            },
        ],
    )
    out = tmp_path / "f.html"
    write_plot_html(log, out)
    page = out.read_text(encoding="utf-8")
    assert page.count('class="friction-line"') == 1
    assert 'class="damper-line"' in page and 'class="inertia-line"' in page
    assert ">pitch gains<" in page and ">roll gains<" in page
