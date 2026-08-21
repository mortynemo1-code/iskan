import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.activity import clipped_duration, validate_interval
from app.schemas import ActivityBatchRequest
from pydantic import ValidationError
from uuid import uuid4


class ActivityIntervalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.start = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)

    def test_valid_interval_is_normalized(self) -> None:
        interval = validate_interval(self.start, self.start + timedelta(minutes=5), "productive")
        self.assertEqual(interval.duration_seconds, 300)
        self.assertEqual(interval.state, "PRODUCTIVE")

    def test_interval_requires_timezone(self) -> None:
        with self.assertRaises(ValueError):
            validate_interval(
                datetime(2026, 8, 20, 9, 0),
                datetime(2026, 8, 20, 9, 5),
                "NEUTRAL",
            )

    def test_negative_interval_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_interval(self.start, self.start - timedelta(seconds=1), "IDLE")

    def test_clipped_duration_counts_only_visible_part(self) -> None:
        result = clipped_duration(
            self.start - timedelta(minutes=10),
            self.start + timedelta(minutes=10),
            self.start,
            self.start + timedelta(hours=1),
        )
        self.assertEqual(result, 600)

    def test_overlapping_events_in_same_session_are_rejected(self) -> None:
        base = {
            "state": "NEUTRAL", "process_name": "code.exe", "windows_session_id": 1,
            "ts_start": self.start, "ts_end": self.start + timedelta(minutes=10),
        }
        with self.assertRaises(ValidationError):
            ActivityBatchRequest(sent_at=self.start, events=[
                {**base, "event_uuid": uuid4()},
                {**base, "event_uuid": uuid4(), "ts_start": self.start + timedelta(minutes=5), "ts_end": self.start + timedelta(minutes=15)},
            ])


if __name__ == "__main__":
    unittest.main()
