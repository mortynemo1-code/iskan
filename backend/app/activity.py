from dataclasses import dataclass
from datetime import datetime

from .presence import normalize_activity_state


MAX_EVENT_DURATION_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class ValidatedInterval:
    start: datetime
    end: datetime
    duration_seconds: int
    state: str


def validate_interval(start: datetime, end: datetime, state: str) -> ValidatedInterval:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Activity timestamps must contain a timezone")
    duration = int((end - start).total_seconds())
    if duration <= 0:
        raise ValueError("Activity event must end after it starts")
    if duration > MAX_EVENT_DURATION_SECONDS:
        raise ValueError("Activity event cannot exceed 24 hours")
    return ValidatedInterval(start, end, duration, normalize_activity_state(state) or "NEUTRAL")


def clipped_duration(start: datetime, end: datetime, range_start: datetime, range_end: datetime) -> int:
    clipped_start = max(start, range_start)
    clipped_end = min(end, range_end)
    return max(0, int((clipped_end - clipped_start).total_seconds()))
