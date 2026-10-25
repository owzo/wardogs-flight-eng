"""Row rendering for the force plot: the shared scale, axis rows and gain rows.

Every row uses the same 0-centred y scale (-1 at the foot, +1 at the head).
An axis row draws spring centre and sine magnitude as lines, pulses as ticks
above (push +) or below (push -) the zero baseline, and transients as short
bars on the row's foot. A gain row draws the condition coefficients (spring,
friction, damper, inertia), which are non-negative and so sit in the upper half.
"""

import html
from typing import Any

Rows = list[dict[str, Any]]
Points = list[tuple[float, float]]

WIDTH, LEFT, RIGHT, TOP, ROW_H, GAP = 980, 64, 24, 64, 170, 26
_AXIS_LINES = (("spring", "center", "spring-line"), ("sine", "magnitude", "sine-line"))
_GAIN_LINES = (
    ("spring", "coefficient", "spring-line coefficient"),
    ("friction", "coefficient", "friction-line"),
    ("damper", "coefficient", "damper-line"),
    ("inertia", "coefficient", "inertia-line"),
)


class Scale:
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


def _polyline(scale: Scale, row: int, points: Points, css: str) -> str:
    coords = " ".join(f"{scale.x(t):.1f},{scale.y(row, v):.1f}" for t, v in points)
    return f'<polyline class="{css}" points="{coords}"/>'


def _pulse(scale: Scale, row: int, event: dict[str, Any]) -> str:
    x = scale.x(event["t"])
    sign = "up" if event["magnitude"] >= 0 else "down"
    return (
        f'<line class="pulse {sign}" x1="{x:.1f}" y1="{scale.y(row, 0.0):.1f}" '
        f'x2="{x:.1f}" y2="{scale.y(row, event["magnitude"]):.1f}"/>'
    )


def _transient(scale: Scale, row: int, event: dict[str, Any]) -> str:
    width = max(2.0, event["duration_s"] * scale.per_second)
    return (
        f'<rect class="transient" x="{scale.x(event["t"]):.1f}" '
        f'y="{scale.y(row, -0.92):.1f}" width="{width:.1f}" height="5"/>'
    )


def _frame(scale: Scale, row: int, title: str) -> list[str]:
    """Row border, dashed zero baseline, title and the ``0`` label."""
    top, base = scale.top(row), scale.y(row, 0.0)
    return [
        f'<rect class="frame" x="{LEFT}" y="{top}" '
        f'width="{WIDTH - LEFT - RIGHT}" height="{ROW_H}"/>',
        f'<line class="baseline" x1="{LEFT}" x2="{WIDTH - RIGHT}" '
        f'y1="{base:.1f}" y2="{base:.1f}"/>',
        f'<text class="title" x="{LEFT}" y="{top - 6}">{html.escape(title)}</text>',
        f'<text class="small" x="{LEFT - 6}" y="{base + 4:.1f}" '
        'text-anchor="end">0</text>',
    ]


def _lines(
    scale: Scale, row: int, axis: str, rows: Rows, lines: tuple[tuple[str, ...], ...]
) -> list[str]:
    drawn = []
    for kind, field, css in lines:
        points = _changes(_series(rows, kind, axis, field))
        if points:
            drawn.append(_polyline(scale, row, points, css))
    return drawn


def axis_row(scale: Scale, row: int, axis: str, rows: Rows) -> str:
    """The force row for one axis: spring centre, sine, pulses and transients."""
    parts = ['<g class="axis-row">', *_frame(scale, row, axis)]
    parts += _lines(scale, row, axis, rows, _AXIS_LINES)
    for event in (r for r in rows if r.get("axis") == axis):
        if event["kind"] == "pulse":
            parts.append(_pulse(scale, row, event))
        elif event["kind"] == "transient":
            parts.append(_transient(scale, row, event))
    return "\n".join([*parts, "</g>"])


def gain_row(scale: Scale, row: int, axis: str, rows: Rows) -> str:
    """The condition-gain row for one axis: the four coefficients over time."""
    parts = ['<g class="gain-row">', *_frame(scale, row, f"{axis} gains")]
    parts += _lines(scale, row, axis, rows, _GAIN_LINES)
    return "\n".join([*parts, "</g>"])
