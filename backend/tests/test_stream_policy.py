from datetime import UTC, datetime

from app.stream_policy_jobs import scheduled_now, within_work_schedule


def test_scheduled_window_uses_employee_timezone() -> None:
    windows = [{"weekdays": [1], "start": "09:00", "end": "18:00"}]
    assert scheduled_now(windows, datetime(2026, 8, 17, 6, 0, tzinfo=UTC), "Asia/Yekaterinburg")
    assert not scheduled_now(windows, datetime(2026, 8, 17, 16, 0, tzinfo=UTC), "Asia/Yekaterinburg")


def test_scheduled_window_supports_overnight() -> None:
    windows = [{"weekdays": [1], "start": "22:00", "end": "06:00"}]
    assert scheduled_now(windows, datetime(2026, 8, 17, 23, 0, tzinfo=UTC), "UTC")
    assert scheduled_now(windows, datetime(2026, 8, 18, 2, 0, tzinfo=UTC), "UTC")


def test_work_schedule_blocks_holiday_and_outside_shift() -> None:
    rule = {"weekdays": [1,2,3,4,5], "start": "09:00", "end": "18:00"}
    instant = datetime(2026, 8, 17, 7, 0, tzinfo=UTC)
    assert within_work_schedule(rule, instant, "Asia/Yekaterinburg", 60)
    assert not within_work_schedule(rule, instant, "Asia/Yekaterinburg", 60, holiday=True)
    assert not within_work_schedule(rule, datetime(2026, 8, 17, 20, 0, tzinfo=UTC), "Asia/Yekaterinburg", 60)
