from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


REPORT_BASES = {"planned", "online", "active"}


def planned_seconds(
    range_start: datetime,
    range_end: datetime,
    timezone_name: str,
    planned_daily_minutes: int,
) -> int:
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = ZoneInfo("UTC")
    local_start = range_start.astimezone(timezone)
    local_end = (range_end - timedelta(microseconds=1)).astimezone(timezone)
    cursor = local_start.date()
    last_date = local_end.date()
    working_days = 0
    while cursor <= last_date:
        if cursor.weekday() < 5:
            working_days += 1
        cursor += timedelta(days=1)
    return working_days * planned_daily_minutes * 60


def percentage(value: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(value * 100 / denominator, 1)


def report_denominator(basis: str, values: dict[str, int]) -> int:
    if basis not in REPORT_BASES:
        raise ValueError("Неизвестная база расчёта")
    if basis == "planned":
        return values["planned_seconds"]
    if basis == "online":
        return values["online_seconds"]
    return values["productive_seconds"] + values["neutral_seconds"] + values["unproductive_seconds"]


def performance_grade(productive_percent: float) -> tuple[str, str]:
    if productive_percent >= 75:
        return "GOOD", "В норме"
    if productive_percent >= 50:
        return "ATTENTION", "Внимание"
    return "RISK", "Риск"
