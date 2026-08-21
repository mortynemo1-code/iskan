from datetime import UTC, datetime

from app.analytics_calculations import performance_grade, percentage, planned_seconds, report_denominator


def test_planned_seconds_counts_weekdays_in_employee_timezone() -> None:
    start = datetime(2026, 8, 17, tzinfo=UTC)  # Monday
    end = datetime(2026, 8, 24, tzinfo=UTC)
    assert planned_seconds(start, end, "UTC", 480) == 5 * 8 * 3600


def test_planned_seconds_falls_back_for_unknown_timezone() -> None:
    start = datetime(2026, 8, 17, tzinfo=UTC)
    end = datetime(2026, 8, 18, tzinfo=UTC)
    assert planned_seconds(start, end, "Mars/Olympus", 420) == 7 * 3600


def test_report_denominators() -> None:
    values = {
        "planned_seconds": 28_800,
        "online_seconds": 25_000,
        "productive_seconds": 18_000,
        "neutral_seconds": 3_000,
        "unproductive_seconds": 1_000,
    }
    assert report_denominator("planned", values) == 28_800
    assert report_denominator("online", values) == 25_000
    assert report_denominator("active", values) == 22_000


def test_percentage_and_grade_thresholds() -> None:
    assert percentage(3, 4) == 75.0
    assert percentage(1, 0) == 0.0
    assert performance_grade(75) == ("GOOD", "В норме")
    assert performance_grade(50) == ("ATTENTION", "Внимание")
    assert performance_grade(49.9) == ("RISK", "Риск")
