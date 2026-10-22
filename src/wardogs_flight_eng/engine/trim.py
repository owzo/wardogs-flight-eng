"""Trim state: the movable centre of the force-feedback spring.

A trim-lock tap captures the stick position as the new centre and a trim-reset
tap returns it to origin. The centre slews linearly toward the requested
target so the stick never snaps; nothing but ``lock`` and ``reset`` ever
changes the target.
"""

_UNIT_LIMIT = 1.0


def _clamp_unit(value: float) -> float:
    """Clamp ``value`` to the normalised stick range ``[-1.0, 1.0]``."""
    return max(-_UNIT_LIMIT, min(_UNIT_LIMIT, value))


def _lerp(start: float, end: float, fraction: float) -> float:
    """Linear interpolation from ``start`` to ``end`` by ``fraction`` (0..1)."""
    return start + (end - start) * fraction


class TrimState:
    """Spring centre on the pitch and roll axes, slewed toward a target.

    Every ``lock``/``reset`` starts a new move from wherever the centre is at
    that moment. Both axes travel in lock-step and arrive together after
    ``slew_s`` seconds, so a full ``0 -> 1`` move on one axis takes exactly
    ``slew_s`` and a shorter move takes the same time at a proportionally
    lower rate.
    """

    def __init__(self, slew_s: float) -> None:
        """Create a centred trim.

        ``slew_s`` is the duration of a move; ``0`` makes the centre snap to
        its target on the next ``step``.
        """
        if slew_s < 0:
            raise ValueError(f"slew_s must be >= 0, got {slew_s}")
        self._slew_s = slew_s
        self._pitch = 0.0
        self._roll = 0.0
        self._start_pitch = 0.0
        self._start_roll = 0.0
        self._target_pitch = 0.0
        self._target_roll = 0.0
        self._elapsed_s = 0.0

    @property
    def center_pitch(self) -> float:
        """Current pitch centre, normalised -1..1."""
        return self._pitch

    @property
    def center_roll(self) -> float:
        """Current roll centre, normalised -1..1."""
        return self._roll

    def lock(self, pitch: float, roll: float) -> None:
        """Slew toward the clamped stick position as the new centre."""
        self._retarget(_clamp_unit(pitch), _clamp_unit(roll))

    def reset(self) -> None:
        """Slew back to the origin."""
        self._retarget(0.0, 0.0)

    def step(self, dt: float) -> None:
        """Advance the current move by ``dt`` seconds (negative counts as zero).

        The centre lands exactly on its target when the move completes.
        """
        self._elapsed_s += max(dt, 0.0)
        if self._elapsed_s >= self._slew_s:
            self._pitch = self._target_pitch
            self._roll = self._target_roll
            return
        fraction = self._elapsed_s / self._slew_s
        self._pitch = _lerp(self._start_pitch, self._target_pitch, fraction)
        self._roll = _lerp(self._start_roll, self._target_roll, fraction)

    def _retarget(self, pitch: float, roll: float) -> None:
        """Begin a new move from the current centre to ``(pitch, roll)``."""
        self._start_pitch = self._pitch
        self._start_roll = self._roll
        self._target_pitch = pitch
        self._target_roll = roll
        self._elapsed_s = 0.0
