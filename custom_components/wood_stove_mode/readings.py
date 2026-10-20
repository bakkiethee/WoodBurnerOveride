"""Evaluation of the redundant temperature sensors at one location."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Reading:
    """One sensor reading.

    ``value`` is None when the entity is unavailable or not numeric. ``age`` is the
    number of seconds since the sensor last updated.
    """

    value: float | None
    age: float = 0.0


@dataclass(frozen=True)
class GroupResult:
    """What the integration knows about one location (two redundant sensors)."""

    value: float | None  # highest valid reading, None when every sensor failed
    failed: tuple[bool, ...]  # one flag per sensor, in the order given
    difference: float | None  # spread between valid readings, None with fewer than two

    @property
    def all_failed(self) -> bool:
        return all(self.failed)

    @property
    def any_failed(self) -> bool:
        return any(self.failed)


def is_failed(
    reading: Reading,
    stale_after: float = 300.0,
    valid_min: float = 0.0,
    valid_max: float = 110.0,
) -> bool:
    """A sensor failed if unavailable, stale for 5 minutes, or outside 0 to 110 °C."""
    if reading.value is None:
        return True
    if reading.age > stale_after:
        return True
    return not (valid_min <= reading.value <= valid_max)


def evaluate_group(
    readings: list[Reading],
    stale_after: float = 300.0,
    valid_min: float = 0.0,
    valid_max: float = 110.0,
) -> GroupResult:
    failed = tuple(is_failed(r, stale_after, valid_min, valid_max) for r in readings)
    valid = [r.value for r, bad in zip(readings, failed) if not bad]
    value = max(valid) if valid else None
    difference = (max(valid) - min(valid)) if len(valid) >= 2 else None
    return GroupResult(value=value, failed=failed, difference=difference)
