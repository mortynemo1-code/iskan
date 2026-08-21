from datetime import UTC, datetime
from pathlib import Path

from app.stream_index_jobs import recording_timestamp


def test_mediamtx_recording_timestamp() -> None:
    assert recording_timestamp(Path("2026-08-19_09-15-00-123456.mp4")) == datetime(2026, 8, 19, 9, 15, 0, 123456, UTC)
    assert recording_timestamp(Path("not-a-recording.mp4")) is None
