import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.presence import calculate_presence, normalize_activity_state


class PresenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)

    def test_recent_heartbeat_is_online(self) -> None:
        result = calculate_presence(
            self.now - timedelta(seconds=30), "productive", now=self.now, ttl_seconds=90
        )
        self.assertTrue(result.is_online)
        self.assertEqual(result.status, "PRODUCTIVE")
        self.assertEqual(result.seconds_since_seen, 30)

    def test_expired_heartbeat_is_offline(self) -> None:
        result = calculate_presence(
            self.now - timedelta(seconds=91), "IDLE", now=self.now, ttl_seconds=90
        )
        self.assertFalse(result.is_online)
        self.assertEqual(result.status, "OFFLINE")

    def test_device_without_heartbeat_is_offline(self) -> None:
        result = calculate_presence(None, None, now=self.now)
        self.assertEqual(result.status, "OFFLINE")
        self.assertIsNone(result.seconds_since_seen)

    def test_unknown_activity_state_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_activity_state("playing")


if __name__ == "__main__":
    unittest.main()
