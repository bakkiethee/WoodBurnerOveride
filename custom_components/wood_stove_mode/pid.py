"""PID controller with fixed gains for the wood stove valve loop.

The controller is evaluated only when the integration decides to change the valves
(at most once every update interval), so the time between calls is the real ``dt``.
Output is a shared valve opening from ``out_min`` to ``out_max`` percent.
"""

from __future__ import annotations


class Pid:
    """Positional PID with conditional-integration anti-windup and bumpless transfer."""

    def __init__(
        self,
        kp: float,
        ki: float,
        kd: float,
        out_min: float = 0.0,
        out_max: float = 100.0,
    ) -> None:
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.out_min = out_min
        self.out_max = out_max
        self._integral = 0.0
        self._last_error: float | None = None
        self._last_time: float | None = None

    def preset(self, output: float, error: float = 0.0) -> None:
        """Continue from ``output`` without a jump, given the error about to be fed in.

        The integral term absorbs the difference between ``output`` and the
        proportional part; the derivative memory is cleared.
        """
        output = min(max(output, self.out_min), self.out_max)
        self._integral = output - self.kp * error
        self._last_error = None
        self._last_time = None

    def update(self, error: float, now: float, freeze_integral: bool = False) -> float:
        """Return the new output for ``error`` (positive error means open further).

        ``freeze_integral`` stops the integral term from growing, for example during an
        emergency. The integral also stops while the output is saturated and the error
        would push it further out of range.
        """
        dt = 0.0 if self._last_time is None else max(now - self._last_time, 0.0)
        derivative = 0.0
        if self._last_error is not None and dt > 0:
            derivative = (error - self._last_error) / dt

        candidate_integral = self._integral + self.ki * error * dt
        raw = self.kp * error + candidate_integral + self.kd * derivative

        saturated = (raw > self.out_max and error > 0) or (
            raw < self.out_min and error < 0
        )
        if freeze_integral:
            raw = self.kp * error + self._integral + self.kd * derivative
        elif not saturated:
            self._integral = candidate_integral

        self._last_error = error
        self._last_time = now
        return min(max(raw, self.out_min), self.out_max)

    def export(self) -> dict:
        return {
            "integral": self._integral,
            "last_error": self._last_error,
            "last_time": self._last_time,
        }

    def restore(self, data: dict) -> None:
        self._integral = float(data.get("integral", 0.0))
        self._last_error = data.get("last_error")
        self._last_time = data.get("last_time")
