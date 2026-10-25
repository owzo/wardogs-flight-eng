"""Held DirectInput effects (springs, conditions, rotor sines): updated in place.

Every held effect has a finite length, so if the loop freezes the base lets
the force time out instead of holding it; staying alive needs a ``Start``
before that length runs out, and the length counts from the last ``Start``.

``HeldEffects`` creates and starts an effect the first time its key plays. A
changed effect is updated with ``SetParameters(DIEP_NORESTART)`` and keeps
playing. A driver that cannot update a playing effect answers
``DIERR_EFFECTPLAYING``; the update is then retried without
``DIEP_NORESTART``, accepting the restart, and the refusal is latched for that
effect kind so later updates go straight to the restart (one INFO line). Any
update whose status carries ``DI_EFFECTRESTARTED`` counts as a ``Start``. An
unchanged effect is started again only after ``silence`` or once more than
half its length has passed since its last ``Start``: about two starts a
second at the 1 s minimum length.
"""

import logging
from dataclasses import dataclass
from functools import partial

from wardogs_flight_eng.engine.commands import Axis
from wardogs_flight_eng.inputs.dinput_api import (
    DI_EFFECTRESTARTED,
    DIERR_EFFECTPLAYING,
    DiEffect,
)
from wardogs_flight_eng.outputs.dinput_channel import (
    DInputChannel,
    ForceFailure,
    attempt,
)
from wardogs_flight_eng.outputs.dinput_effects import silenced

log = logging.getLogger(__name__)

EffectKey = tuple[str, Axis]


@dataclass(slots=True)
class _Held:
    effect_id: int
    effect: DiEffect
    started_at: float | None  # None: start on the next tick whatever it holds


class HeldEffects:
    """The held effects of one DirectInput device, by kind and axis."""

    def __init__(self, channel: DInputChannel, length_s: float) -> None:
        self._channel = channel
        self._restart_after_s = length_s / 2
        self._held: dict[EffectKey, _Held] = {}
        self._restarted: set[EffectKey] = set()
        self.restart_latched: dict[str, bool] = {}

    @property
    def effect_ids(self) -> list[int]:
        return [held.effect_id for held in self._held.values()]

    def due(self, t: float, key: EffectKey, steady: DiEffect) -> bool:
        """Whether ``key`` must be created, updated or started this tick.

        ``steady`` is the effect as it would be with nothing restarted. A held
        effect equal to it and started at most half a length ago is left
        playing.
        """
        held = self._held.get(key)
        if held is None or held.started_at is None:
            return True
        return steady != held.effect or t - held.started_at > self._restart_after_s

    def play(self, t: float, key: EffectKey, effect: DiEffect) -> None:
        """Create and start ``effect`` if new; update it in place if changed;
        start it when it is not running or its half-life has passed."""
        self._restarted.discard(key)
        held = self._held.get(key)
        if held is None:
            held = _Held(self._channel.create(effect), effect, None)
            self._held[key] = held
        elif effect != held.effect:
            restarted = self._update(held.effect_id, effect)
            held.effect = effect
            if restarted:
                self._mark_started(t, key, held)
        due_start = held.started_at is None or (
            t - held.started_at > self._restart_after_s
        )
        if due_start:
            self._channel.start(held.effect_id)
            self._mark_started(t, key, held)

    def restarted(self, key: EffectKey) -> bool:
        """Whether the last ``play`` of ``key`` (re)started the effect from its
        start; valid only immediately after that ``play``.

        No production code calls this today: ``HeldSines`` re-anchors its
        phase clock on every send. It is kept as the hook for switching the
        sines to hold their phase between ``Start`` calls (re-anchoring only
        when this is true) if the hardware shows a phase jump on in-place
        updates.
        """
        return key in self._restarted

    def silence(self, failures: list[ForceFailure]) -> None:
        """Zero every held effect so no later start resurrects a force.

        Each is due again on the next tick. A failing update is recorded in
        ``failures`` and the rest are still attempted.
        """
        for held in self._held.values():
            held.effect = silenced(held.effect)
            held.started_at = None
            attempt(failures, partial(self._update, held.effect_id, held.effect))

    def _mark_started(self, t: float, key: EffectKey, held: _Held) -> None:
        held.started_at = t
        self._restarted.add(key)

    def _update(self, effect_id: int, effect: DiEffect) -> bool:
        """Update in place, else (latched per kind) with a restart; whether the
        effect restarted."""
        kind = effect.kind
        if not self.restart_latched.get(kind, False):
            status = self._channel.update(effect_id, effect, norestart=True)
            if status != DIERR_EFFECTPLAYING:
                return bool(status & DI_EFFECTRESTARTED)
            self.restart_latched[kind] = True
            log.info(
                "%s: the driver cannot update a playing effect in place; "
                "updates will restart it",
                kind,
            )
        status = self._channel.update(effect_id, effect, norestart=False)
        return bool(status & DI_EFFECTRESTARTED)
