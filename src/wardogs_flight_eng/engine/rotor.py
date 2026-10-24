"""Rotor model: main-rotor RPM and the vibration it drives.

The rotor spools up linearly from zero when running and spools down at the
game's fixed RPM-per-second rate when toggled off. The 1/rev vibration
frequency is ``rpm / 60`` Hz and its amplitude follows the collective, with a
boost for cyclic deflection away from the trim centre.
"""

_SECONDS_PER_MINUTE = 60.0


class RotorModel:
    """Main-rotor RPM state with a collective- and cyclic-driven buzz amplitude.

    Takes plain floats rather than game constants so it stays independently
    testable.
    """

    def __init__(
        self,
        operating_rpm: float,
        spool_up_s: float,
        spool_down_rpm_per_s: float,
        base_amplitude: float,
        deflection_factor: float,
        airspeed_factor: float = 0.0,
    ) -> None:
        """Create a rotor that is running and at rest (0 RPM).

        ``spool_up_s`` is the time to go from 0 to ``operating_rpm``; ``0``
        reaches operating RPM on the next ``step``.
        """
        if operating_rpm <= 0:
            raise ValueError(f"operating_rpm must be > 0, got {operating_rpm}")
        for name, value in (
            ("spool_up_s", spool_up_s),
            ("spool_down_rpm_per_s", spool_down_rpm_per_s),
            ("base_amplitude", base_amplitude),
            ("deflection_factor", deflection_factor),
            ("airspeed_factor", airspeed_factor),
        ):
            if value < 0:
                raise ValueError(f"{name} must be >= 0, got {value}")
        self._operating_rpm = operating_rpm
        self._spool_up_s = spool_up_s
        self._spool_down_rpm_per_s = spool_down_rpm_per_s
        self._base_amplitude = base_amplitude
        self._deflection_factor = deflection_factor
        self._airspeed_factor = airspeed_factor
        self.running = True
        self.rpm = 0.0

    @property
    def frequency_hz(self) -> float:
        """1/rev vibration frequency in Hz (``rpm / 60``)."""
        return self.rpm / _SECONDS_PER_MINUTE

    @property
    def spool_fraction(self) -> float:
        """Current RPM as a fraction of operating RPM (``rpm / operating_rpm``)."""
        return self.rpm / self._operating_rpm

    def take_over(self, spool_fraction: float, running: bool) -> None:
        """Adopt another rotor's spool state, scaled to this rotor's operating RPM.

        ``spool_fraction`` is clamped to ``0..1`` first.
        """
        self.rpm = max(0.0, min(1.0, spool_fraction)) * self._operating_rpm
        self.running = running

    def toggle(self) -> None:
        """Switch between running (spooling up) and stopped (spooling down)."""
        self.running = not self.running

    def step(self, dt: float) -> None:
        """Advance the spool by ``dt`` seconds (negative counts as zero)."""
        dt = max(dt, 0.0)
        if self.running:
            self.rpm = self._spool_up(dt)
        else:
            self.rpm = max(0.0, self.rpm - self._spool_down_rpm_per_s * dt)

    def amplitude(
        self, collective: float, deflection: float, airspeed: float = 0.0
    ) -> float:
        """Buzz amplitude clamped to ``0..1``.

        ``collective`` is the normalised collective ``0..1`` and
        ``deflection`` the cyclic's distance from the trim centre ``0..1``.
        ``airspeed`` is the normalised airspeed estimate ``0..1``.
        """
        raw = (
            self._base_amplitude
            * self.spool_fraction
            * collective
            * (1.0 + self._deflection_factor * deflection)
            * (1.0 + self._airspeed_factor * airspeed)
        )
        return max(0.0, min(1.0, raw))

    def _spool_up(self, dt: float) -> float:
        """RPM after ``dt`` seconds of spooling up, capped at operating RPM."""
        if self._spool_up_s == 0:
            return self._operating_rpm
        rate = self._operating_rpm / self._spool_up_s
        return min(self._operating_rpm, self.rpm + rate * dt)
