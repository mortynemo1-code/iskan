from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


ALLOWED_ACTIVITY_STATES = {
    "PRODUCTIVE",
    "NEUTRAL",
    "UNPRODUCTIVE",
    "IDLE",
    "LOCKED",
    "BREAK",
}


@dataclass(frozen=True)
class PresenceSnapshot:
    is_online: bool
    status: str
    seconds_since_seen: int | None


def normalize_activity_state(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    if normalized not in ALLOWED_ACTIVITY_STATES:
        raise ValueError(f"Unsupported activity state: {value}")
    return normalized


def calculate_presence(
    last_seen: datetime | None,
    activity_state: str | None,
    *,
    now: datetime | None = None,
    ttl_seconds: int = 90,
) -> PresenceSnapshot:
    if last_seen is None:
        return PresenceSnapshot(False, "OFFLINE", None)
    current = now or datetime.now(UTC)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    elapsed = max(0, int((current - last_seen).total_seconds()))
    is_online = current - last_seen <= timedelta(seconds=ttl_seconds)
    status = normalize_activity_state(activity_state) if is_online else "OFFLINE"
    return PresenceSnapshot(is_online, status or "ONLINE", elapsed)
