"""Index MediaMTX fMP4 recordings from the shared recording volume."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from .config import get_settings
from .database import connection
from .storage import ObjectStorage


def recording_timestamp(path: Path) -> datetime | None:
    value = path.stem
    for pattern in ("%Y-%m-%d_%H-%M-%S-%f", "%Y-%m-%d_%H-%M-%S"):
        try: return datetime.strptime(value, pattern).replace(tzinfo=UTC)
        except ValueError: continue
    return None


async def index_stream_segments_once() -> int:
    root = Path(get_settings().video_recording_root).resolve()
    if not root.is_dir(): return 0
    indexed = 0
    storage = ObjectStorage()
    async for conn in connection():
        sessions = await conn.fetch("SELECT id,stream_key FROM stream_sessions")
        for session in sessions:
            directory = (root / session["stream_key"]).resolve()
            if root not in directory.parents or not directory.is_dir(): continue
            files = []
            for path in directory.rglob("*.mp4"):
                stamp = recording_timestamp(path)
                if stamp is not None and path.is_file(): files.append((stamp, path))
            files.sort(key=lambda item: item[0])
            for index, (stamp, path) in enumerate(files):
                next_stamp = files[index + 1][0] if index + 1 < len(files) else None
                duration_ms = int(max(1000, min(300_000, ((next_stamp or datetime.fromtimestamp(path.stat().st_mtime, UTC)) - stamp).total_seconds() * 1000)))
                relative = path.resolve().relative_to(root).as_posix()
                storage_key = f"video/{relative}"
                sequence = int(stamp.timestamp())
                size = path.stat().st_size
                existing = await conn.fetchrow("SELECT size_bytes,storage_key FROM stream_segments WHERE session_id=$1 AND seq=$2", session["id"], sequence)
                if existing is None or existing["size_bytes"] != size or existing["storage_key"] != storage_key:
                    await storage.put_file(storage_key, str(path), "video/mp4")
                await conn.execute(
                    """INSERT INTO stream_segments(session_id,seq,ts_start,duration_ms,storage_key,size_bytes,expires_at)
                       VALUES($1,$2,$3,$4,$5,$6,$3+interval '7 days')
                       ON CONFLICT(session_id,seq) DO UPDATE SET duration_ms=EXCLUDED.duration_ms,
                         storage_key=EXCLUDED.storage_key,size_bytes=EXCLUDED.size_bytes""",
                    session["id"], sequence, stamp, duration_ms, storage_key, size,
                )
                indexed += 1
        return indexed
    return indexed


async def stream_index_worker() -> None:
    while True:
        try: await index_stream_segments_once()
        except asyncio.CancelledError: raise
        except Exception: pass
        await asyncio.sleep(30)
