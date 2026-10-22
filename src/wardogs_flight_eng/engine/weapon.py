"""Weapon model: fire-button hold -> recoil events at the game's exact fire rate.

Holding fire runs the weapon's wind-up, then emits one recoil event per round
at ``rounds_per_minute``. A Reload tap silences the weapon for ``reload_s``;
if fire is still held when the window ends, the wind-up starts over.

Timing convention: the first round fires the instant firing begins and every
later round one interval after the previous one. A round that would land
exactly on the end of a tick belongs to the next tick, so a tick of ``n``
intervals never yields more than ``n`` rounds. Wind-up completing exactly at a
tick boundary therefore returns no round until the next tick.
"""

import math
from typing import Literal

from wardogs_flight_eng.constants.model import Shake, Weapon

WeaponState = Literal["idle", "winding", "firing", "reloading"]

_EPSILON_S = 1e-9


def scaled(
    vector: tuple[float, float], pattern: tuple[tuple[float, float], ...]
) -> tuple[float, float]:
    """``vector`` divided by the length of the longest vector in ``pattern``.

    An empty or all-zero pattern has nothing to normalise against, so the
    vector is returned unchanged.
    """
    longest = max((math.hypot(*step) for step in pattern), default=0.0)
    if longest <= 0.0:
        return vector
    return (vector[0] / longest, vector[1] / longest)


class WeaponModel:
    """Wind-up, fire-rate and reload state machine for one weapon."""

    def __init__(
        self,
        weapon: Weapon,
        amplitude: float,
        rocket_kick: tuple[float, float] = (0.0, -1.0),
        shake: Shake | None = None,
    ) -> None:
        """Create an idle weapon.

        ``amplitude`` scales every recoil event, ``rocket_kick`` is the unit
        ``(roll, pitch)`` direction used by weapons without a recoil pattern,
        and ``shake`` is the weapon's camera-shake envelope resolved by the
        caller from the constants.
        """
        if weapon.rounds_per_minute <= 0:
            raise ValueError(
                f"rounds_per_minute must be > 0, got {weapon.rounds_per_minute}"
            )
        if weapon.windup_s < 0 or weapon.reload_s < 0:
            raise ValueError("windup_s and reload_s must be >= 0")
        if amplitude < 0:
            raise ValueError(f"amplitude must be >= 0, got {amplitude}")
        self._weapon = weapon
        self._rocket_kick = rocket_kick
        self._interval_s = 60.0 / weapon.rounds_per_minute
        multiplier = 1.0 if weapon.shake_multiplier is None else weapon.shake_multiplier
        self._gain = amplitude * multiplier
        self.shake = shake
        self._state: WeaponState = "idle"
        self._windup_elapsed_s = 0.0
        self._since_round_s = self._interval_s
        self._reload_left_s = 0.0
        self._pattern_index = 0

    @property
    def state(self) -> WeaponState:
        """Current phase of the weapon."""
        return self._state

    def scaled(self, vector: tuple[float, float]) -> tuple[float, float]:
        """``vector`` divided by the longest vector in this weapon's pattern."""
        return scaled(vector, self._weapon.recoil_pattern)

    def step(
        self, dt: float, fire_held: bool, reload_tapped: bool
    ) -> list[tuple[float, float]]:
        """Advance ``dt`` seconds (negative counts as zero).

        Returns the ``(roll, pitch)`` recoil of each round fired in the tick.
        ``reload_tapped`` is an edge the caller has already detected.
        """
        remaining = max(dt, 0.0)
        if reload_tapped and self._state != "reloading":
            self._state = "reloading"
            self._reload_left_s = self._weapon.reload_s
        if self._state == "reloading":
            remaining = self._run_reload(remaining)
            if self._state == "reloading":
                return []
        if not fire_held:
            self._release()
            return []
        if self._state == "idle":
            self._state = "winding"
            self._windup_elapsed_s = 0.0
        if self._state == "winding":
            remaining = self._run_windup(remaining)
        if self._state != "firing":
            return []
        return self._run_firing(remaining)

    def _run_reload(self, remaining: float) -> float:
        """Spend ``remaining`` on the reload window; leave it when it ends."""
        spent = min(remaining, self._reload_left_s)
        self._reload_left_s -= spent
        if self._reload_left_s <= _EPSILON_S:
            self._release()
        return remaining - spent

    def _release(self) -> None:
        """Return to idle and forget any wind-up progress."""
        self._state = "idle"
        self._windup_elapsed_s = 0.0

    def _run_windup(self, remaining: float) -> float:
        """Spend ``remaining`` on wind-up; enter firing when it completes."""
        needed = self._weapon.windup_s - self._windup_elapsed_s
        if remaining + _EPSILON_S < needed:
            self._windup_elapsed_s += remaining
            return 0.0
        self._state = "firing"
        self._since_round_s = self._interval_s
        return max(remaining - needed, 0.0)

    def _run_firing(self, remaining: float) -> list[tuple[float, float]]:
        """Emit a round each time the interval accumulator is full."""
        rounds: list[tuple[float, float]] = []
        while remaining > _EPSILON_S:
            if self._since_round_s >= self._interval_s - _EPSILON_S:
                rounds.append(self._next_round())
                self._since_round_s = 0.0
                continue
            advance = min(self._interval_s - self._since_round_s, remaining)
            self._since_round_s += advance
            remaining -= advance
        return rounds

    def _next_round(self) -> tuple[float, float]:
        """Recoil of the next round: pattern step for MGs, kick otherwise."""
        pattern = self._weapon.recoil_pattern
        if not pattern:
            direction = self._rocket_kick
        else:
            yaw, pitch = self.scaled(pattern[self._pattern_index % len(pattern)])
            self._pattern_index += 1
            direction = (yaw, pitch)
        return (direction[0] * self._gain, direction[1] * self._gain)
