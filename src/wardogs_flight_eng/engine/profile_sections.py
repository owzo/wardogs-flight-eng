"""Profile sections: feel, rotor buzz, recoil, safety and the airspeed estimator.

Every value in these sections is owner taste; ``profile.py`` assembles them
into one airframe ``Profile`` and checks gains against the force ceiling.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from wardogs_flight_eng.engine.device_map import ProfileModel

Unit = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
SignedUnit = Annotated[float, Field(ge=-1, le=1, allow_inf_nan=False)]
NonNegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Positive = Annotated[float, Field(gt=0, allow_inf_nan=False)]

FeelMode = Literal["force_trim", "unboosted"]
"""``force_trim``: spring re-centred by trim lock. ``unboosted``: centre fixed,
trim lock blends the spring into ``clamp_friction``."""


class Feel(ProfileModel):
    """Centring spring plus friction, damper and inertia conditions.

    Roll static forces are ``* roll_scale``; damper and inertia are equal on
    both axes. ``clamp_friction`` exists only in ``unboosted`` mode.
    """

    mode: FeelMode
    spring_coefficient: Unit
    roll_scale: Unit = 0.5
    deadband: Unit
    trim_slew_s: NonNegative
    friction: Unit
    clamp_friction: Unit | None = None
    damper: Unit
    inertia: Unit

    @model_validator(mode="after")
    def _check_friction_rules(self) -> Self:
        """Friction stays under a quarter of the spring; the clamp is unboosted-only."""
        limit = self.spring_coefficient / 4
        if self.friction > limit:
            raise ValueError(
                f"feel.friction {self.friction} must be <= "
                f"spring_coefficient / 4 ({limit})"
            )
        if self.mode == "force_trim":
            if self.clamp_friction is not None:
                raise ValueError(
                    "feel.clamp_friction is only valid when feel.mode is 'unboosted'"
                )
            return self
        if self.clamp_friction is None:
            raise ValueError(
                "feel.clamp_friction is required when feel.mode is 'unboosted'"
            )
        if self.clamp_friction < self.friction:
            raise ValueError(
                f"feel.clamp_friction {self.clamp_friction} must be >= "
                f"feel.friction {self.friction}"
            )
        return self


class Rotor(ProfileModel):
    """Rotor buzz. ``None`` spool-down falls back to the airframe's constant.

    ``airspeed_factor`` scales the amplitude by ``1 + factor * airspeed``.
    ``min_amplitude`` is the buzz floor: a magnitude strictly below it is
    emitted as 0.0, at or above it plays unchanged.
    """

    base_amplitude: Unit
    deflection_factor: NonNegative
    spool_up_s: NonNegative
    spool_down_rpm_per_s: Positive | None
    airspeed_factor: NonNegative
    min_amplitude: Unit = 0.0


class Recoil(ProfileModel):
    """Recoil pulse gain, ``(roll, pitch)`` rocket kick and shake magnitude."""

    amplitude: Unit
    rocket_kick: tuple[SignedUnit, SignedUnit]
    shake_amplitude: Unit


class Safety(ProfileModel):
    """Backend force ceiling and the engine's stalled-tick watchdog."""

    force_ceiling: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)] = 0.6
    watchdog_s: Positive = 0.25


class Estimator(ProfileModel):
    """Airspeed estimate from forward cyclic: input above ``forward_threshold``
    drives a first-order lag with time constant ``tau_s`` (0 snaps)."""

    kind: Literal["input"]
    forward_threshold: Annotated[float, Field(ge=0, lt=1, allow_inf_nan=False)]
    tau_s: NonNegative
