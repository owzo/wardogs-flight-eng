"""Render a JSONL force log as one self-contained HTML page of inline SVG.

Four rows share a time axis in seconds: ``pitch`` and ``roll`` force rows
(spring centre and sine magnitude as lines, pulses and transients as marks),
then ``pitch gains`` and ``roll gains`` (spring coefficient, friction, damper
and inertia as lines). ``all_off`` spans cross every row. Row drawing lives in
``plot_rows``; this module assembles the page. No scripts, fonts or links.
"""

import html
import json
from pathlib import Path

from wardogs_flight_eng.runtime.plot_rows import (
    GAP,
    LEFT,
    RIGHT,
    ROW_H,
    TOP,
    WIDTH,
    Rows,
    Scale,
    axis_row,
    gain_row,
)

AXES = ("pitch", "roll")
FOOT = 52
ROW_COUNT = 2 * len(AXES)
BOTTOM = TOP + ROW_COUNT * ROW_H + (ROW_COUNT - 1) * GAP
HEIGHT = BOTTOM + FOOT
_TICK_STEPS = (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600)
_LEGEND = (
    ("spring-line", "spring centre"),
    ("sine-line", "sine magnitude"),
    ("spring-line coefficient", "spring coefficient"),
    ("friction-line", "friction"),
    ("damper-line", "damper"),
    ("inertia-line", "inertia"),
    ("pulse up", "pulse (sign: above / below 0)"),
    ("transient", "transient (bar = duration)"),
    ("all-off", "all off"),
)
_CSS = """
:root{--bg:#fff;--fg:#1d2230;--grid:#d5d9e2;--spring:#1f6fd1;--sine:#d9731a;
--pulse:#2a8a4a;--transient:#8a4fc4;--off:#c4262e;--friction:#b8326e;
--damper:#11807a;--inertia:#6b6f2a}
@media(prefers-color-scheme:dark){:root{--bg:#14171f;--fg:#e4e7ee;--grid:#3a4050;
--spring:#6aa8ff;--sine:#ffa24d;--pulse:#5fd183;--transient:#c59bff;--off:#ff6b72;
--friction:#ff7eb6;--damper:#4fd6cb;--inertia:#d6d66b}}
body{margin:16px;background:var(--bg);color:var(--fg);
font:13px system-ui,sans-serif}svg{max-width:100%;height:auto}
text{fill:var(--fg)}.frame{stroke:var(--grid);fill:none}
.baseline{stroke:var(--grid);stroke-dasharray:4 3}.title{font-weight:600}
.spring-line{stroke:var(--spring);fill:none;stroke-width:1.6}
.sine-line{stroke:var(--sine);fill:none;stroke-width:1.2}
.coefficient{stroke-dasharray:6 3}
.friction-line{stroke:var(--friction);fill:none;stroke-width:1.6}
.damper-line{stroke:var(--damper);fill:none;stroke-width:1.4}
.inertia-line{stroke:var(--inertia);fill:none;stroke-width:1.4}
.pulse{stroke:var(--pulse);stroke-width:1.4}.transient{fill:var(--transient)}
.all-off{stroke:var(--off);stroke-width:2}.all-off-span{fill:var(--off);opacity:.12}
.tick-label,.small{font-size:11px}.title{font-size:14px}
"""


def _all_off_runs(rows: Rows) -> list[list[float]]:
    """``[start, end]`` per run of consecutive ``all_off`` ticks."""
    times = sorted({r["t"] for r in rows})
    period = min((b - a for a, b in zip(times, times[1:], strict=False)), default=0.01)
    runs: list[list[float]] = []
    for t in sorted(r["t"] for r in rows if r["kind"] == "all_off"):
        if runs and t - runs[-1][1] <= 1.5 * period:
            runs[-1][1] = t
        else:
            runs.append([t, t])
    return runs


def _all_off_marks(scale: Scale, rows: Rows) -> list[str]:
    marks = []
    for start, end in _all_off_runs(rows):
        x0, x1 = scale.x(start), scale.x(end)
        marks.append(
            f'<rect class="all-off-span" x="{x0:.1f}" y="{TOP}" '
            f'width="{x1 - x0:.1f}" height="{BOTTOM - TOP}"/>'
            f'<line class="all-off" x1="{x0:.1f}" x2="{x0:.1f}" '
            f'y1="{TOP}" y2="{BOTTOM}"/>'
        )
    return marks


def _time_axis(scale: Scale, t_max: float) -> list[str]:
    step = next((s for s in _TICK_STEPS if t_max / s <= 12), _TICK_STEPS[-1])
    marks = []
    for n in range(int(t_max / step + 1e-9) + 1):
        x = scale.x(n * step)
        marks.append(
            f'<line class="frame" x1="{x:.1f}" x2="{x:.1f}" y1="{BOTTOM}" '
            f'y2="{BOTTOM + 5}"/><text class="tick-label" x="{x:.1f}" '
            f'y="{BOTTOM + 18}" text-anchor="middle">{n * step:g}</text>'
        )
    mid = (LEFT + WIDTH - RIGHT) / 2
    marks.append(
        f'<text x="{mid}" y="{BOTTOM + 38}" text-anchor="middle">time (s)</text>'
    )
    return marks


def _legend() -> str:
    """Key swatches, wrapped onto a second line when the first is full."""
    parts, x, y = [], LEFT, 24
    for css, label in _LEGEND:
        width = 33 + 6 * len(label)
        if x + width > WIDTH - RIGHT:
            x, y = LEFT, y + 18
        if css == "transient":
            swatch = (
                f'<rect class="key {css}" x="{x}" y="{y - 2}" width="14" height="5"/>'
            )
        else:
            swatch = (
                f'<line class="key {css}" x1="{x}" x2="{x + 14}" y1="{y}" y2="{y}"/>'
            )
        text = f'<text class="small" x="{x + 19}" y="{y + 4}">{label}</text>'
        parts.append(swatch + text)
        x += width
    return f'<g class="legend">{"".join(parts)}</g>'


def write_plot_html(log_path: Path, out_path: Path) -> None:
    """Read the JSONL force log and write the standalone HTML plot."""
    text = Path(log_path).read_text(encoding="utf-8")
    rows: Rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    t_max = max((r["t"] for r in rows), default=0.0) or 1.0
    scale = Scale(t_max)
    body = [_legend()]
    body += [axis_row(scale, i, axis, rows) for i, axis in enumerate(AXES)]
    body += [gain_row(scale, len(AXES) + i, a, rows) for i, a in enumerate(AXES)]
    body += _all_off_marks(scale, rows) + _time_axis(scale, t_max)
    page = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Wardogs Flight Eng force plot</title><style>{_CSS}</style></head>"
        f"<body><h1>Force log: {html.escape(Path(log_path).name)}</h1>"
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" '
        f'width="{WIDTH}" role="img" aria-label="Force commands over time">'
        f"{''.join(body)}</svg></body></html>\n"
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
