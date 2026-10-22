"""Render a JSONL force log as one self-contained HTML page of inline SVG.

Two rows (pitch, roll) share a time axis in seconds: spring centre and sine
magnitude as lines, pulses as ticks above (push +) or below (push -) the zero
baseline, transients as short bars on the row's foot. ``all_off`` spans cross
both rows. No scripts, fonts or links.
"""

import html
import json
from pathlib import Path
from typing import Any

Rows = list[dict[str, Any]]
Points = list[tuple[float, float]]

AXES = ("pitch", "roll")
WIDTH, LEFT, RIGHT, TOP, ROW_H, GAP, FOOT = 980, 64, 24, 64, 170, 26, 52
BOTTOM = TOP + 2 * ROW_H + GAP
HEIGHT = BOTTOM + FOOT
_TICK_STEPS = (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600)
_LINES = (("spring", "center", "spring-line"), ("sine", "magnitude", "sine-line"))
_LEGEND = (
    ("spring-line", "spring centre"),
    ("sine-line", "sine magnitude"),
    ("pulse up", "pulse (sign: above / below 0)"),
    ("transient", "transient (bar = duration)"),
    ("all-off", "all off"),
)
_CSS = """
:root{--bg:#fff;--fg:#1d2230;--grid:#d5d9e2;--spring:#1f6fd1;--sine:#d9731a;
--pulse:#2a8a4a;--transient:#8a4fc4;--off:#c4262e}
@media(prefers-color-scheme:dark){:root{--bg:#14171f;--fg:#e4e7ee;--grid:#3a4050;
--spring:#6aa8ff;--sine:#ffa24d;--pulse:#5fd183;--transient:#c59bff;--off:#ff6b72}}
body{margin:16px;background:var(--bg);color:var(--fg);
font:13px system-ui,sans-serif}svg{max-width:100%;height:auto}
text{fill:var(--fg)}.frame{stroke:var(--grid);fill:none}
.baseline{stroke:var(--grid);stroke-dasharray:4 3}.title{font-weight:600}
.spring-line{stroke:var(--spring);fill:none;stroke-width:1.6}
.sine-line{stroke:var(--sine);fill:none;stroke-width:1.2}.pulse{stroke:var(--pulse);stroke-width:1.4}.transient{fill:var(--transient)}
.all-off{stroke:var(--off);stroke-width:2}.all-off-span{fill:var(--off);opacity:.12}
.tick-label,.small{font-size:11px}.title{font-size:14px}
"""


class _Scale:
    """Maps time to x, and a -1..1 value to y within a row."""

    def __init__(self, t_max: float) -> None:
        self.per_second = (WIDTH - LEFT - RIGHT) / t_max

    def x(self, t: float) -> float:
        return LEFT + t * self.per_second

    @staticmethod
    def top(row: int) -> float:
        return TOP + row * (ROW_H + GAP)

    def y(self, row: int, value: float) -> float:
        clipped = max(-1.0, min(1.0, value))
        return self.top(row) + ROW_H / 2 * (1 - 0.95 * clipped)


def _series(rows: Rows, kind: str, axis: str, field: str) -> Points:
    return [(r["t"], r[field]) for r in rows if r["kind"] == kind and r["axis"] == axis]


def _changes(points: Points) -> Points:
    """Drop points inside flat runs; linear interpolation redraws them exactly."""
    last = len(points) - 1
    return [
        p
        for i, p in enumerate(points)
        if i in (0, last) or p[1] != points[i - 1][1] or p[1] != points[i + 1][1]
    ]


def _polyline(scale: _Scale, row: int, points: Points, css: str) -> str:
    coords = " ".join(f"{scale.x(t):.1f},{scale.y(row, v):.1f}" for t, v in points)
    return f'<polyline class="{css}" points="{coords}"/>'


def _pulse(scale: _Scale, row: int, event: dict[str, Any]) -> str:
    x = scale.x(event["t"])
    sign = "up" if event["magnitude"] >= 0 else "down"
    return (
        f'<line class="pulse {sign}" x1="{x:.1f}" y1="{scale.y(row, 0.0):.1f}" '
        f'x2="{x:.1f}" y2="{scale.y(row, event["magnitude"]):.1f}"/>'
    )


def _transient(scale: _Scale, row: int, event: dict[str, Any]) -> str:
    width = max(2.0, event["duration_s"] * scale.per_second)
    return (
        f'<rect class="transient" x="{scale.x(event["t"]):.1f}" '
        f'y="{scale.y(row, -0.92):.1f}" width="{width:.1f}" height="5"/>'
    )


def _axis_row(scale: _Scale, row: int, axis: str, rows: Rows) -> str:
    top, base = scale.top(row), scale.y(row, 0.0)
    parts = [
        '<g class="axis-row">',
        f'<rect class="frame" x="{LEFT}" y="{top}" '
        f'width="{WIDTH - LEFT - RIGHT}" height="{ROW_H}"/>',
        f'<line class="baseline" x1="{LEFT}" x2="{WIDTH - RIGHT}" '
        f'y1="{base:.1f}" y2="{base:.1f}"/>',
        f'<text class="title" x="{LEFT}" y="{top - 6}">{html.escape(axis)}</text>',
        f'<text class="small" x="{LEFT - 6}" y="{base + 4:.1f}" '
        'text-anchor="end">0</text>',
    ]
    for kind, field, css in _LINES:
        points = _changes(_series(rows, kind, axis, field))
        if points:
            parts.append(_polyline(scale, row, points, css))
    for event in (r for r in rows if r.get("axis") == axis):
        if event["kind"] == "pulse":
            parts.append(_pulse(scale, row, event))
        elif event["kind"] == "transient":
            parts.append(_transient(scale, row, event))
    return "\n".join([*parts, "</g>"])


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


def _all_off_marks(scale: _Scale, rows: Rows) -> list[str]:
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


def _time_axis(scale: _Scale, t_max: float) -> list[str]:
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
    parts, x = [], LEFT
    for css, label in _LEGEND:
        if css == "transient":
            swatch = f'<rect class="key {css}" x="{x}" y="22" width="14" height="5"/>'
        else:
            swatch = f'<line class="key {css}" x1="{x}" x2="{x + 14}" y1="24" y2="24"/>'
        parts.append(f'{swatch}<text class="small" x="{x + 19}" y="28">{label}</text>')
        x += 33 + 6 * len(label)
    return f'<g class="legend">{"".join(parts)}</g>'


def write_plot_html(log_path: Path, out_path: Path) -> None:
    """Read the JSONL force log and write the standalone HTML plot."""
    text = Path(log_path).read_text(encoding="utf-8")
    rows: Rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    t_max = max((r["t"] for r in rows), default=0.0) or 1.0
    scale = _Scale(t_max)
    body = [_legend()]
    body += [_axis_row(scale, i, axis, rows) for i, axis in enumerate(AXES)]
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
