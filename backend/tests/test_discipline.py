from datetime import UTC, date, datetime

from app.discipline import shift_bounds


def test_shift_bounds_respects_employee_timezone():
    bounds = shift_bounds(
        date(2026, 8, 21),
        {"weekdays": [1, 2, 3, 4, 5], "start": "09:00", "end": "18:00"},
        "Asia/Yekaterinburg",
    )
    assert bounds == (
        datetime(2026, 8, 21, 4, 0, tzinfo=UTC),
        datetime(2026, 8, 21, 13, 0, tzinfo=UTC),
    )


def test_shift_bounds_skips_weekend():
    assert shift_bounds(
        date(2026, 8, 22),
        {"weekdays": [1, 2, 3, 4, 5], "start": "09:00", "end": "18:00"},
        "UTC",
    ) is None


def test_shift_bounds_handles_overnight_shift():
    start, end = shift_bounds(
        date(2026, 8, 21), {"weekdays": [5], "start": "22:00", "end": "06:00"}, "UTC"
    )
    assert end > start
    assert (end - start).total_seconds() == 8 * 3600
