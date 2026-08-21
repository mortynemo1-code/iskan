from datetime import UTC, datetime

from app.report_jobs import cron_matches, next_cron_after


def test_weekly_cron_matches_monday_at_eight():
    assert cron_matches("0 8 * * 1", datetime(2026, 8, 24, 8, 0, tzinfo=UTC))
    assert not cron_matches("0 8 * * 1", datetime(2026, 8, 25, 8, 0, tzinfo=UTC))


def test_daily_cron_next_run():
    instant = datetime(2026, 8, 21, 10, 15, tzinfo=UTC)
    assert next_cron_after("30 10 * * *", instant) == datetime(2026, 8, 21, 10, 30, tzinfo=UTC)


def test_monthly_cron():
    assert cron_matches("0 9 1 * *", datetime(2026, 9, 1, 9, 0, tzinfo=UTC))
