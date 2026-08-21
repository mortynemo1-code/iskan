import asyncio
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import get_settings
from .database import connection
from .storage import ObjectStorage


async def _effective_days(conn, data_type: str, employee_id, department_id) -> int:
    value = await conn.fetchval(
        """SELECT days FROM retention_policies WHERE data_type=$1 AND (
             (scope_type='employee' AND scope_id=$2) OR (scope_type='department' AND scope_id=$3) OR scope_type='global')
           ORDER BY CASE scope_type WHEN 'employee' THEN 1 WHEN 'department' THEN 2 ELSE 3 END LIMIT 1""",
        data_type, employee_id, department_id,
    )
    return int(value or {"screenshots": 30, "video": 7, "events": 365}[data_type])


async def purge_screenshots(conn) -> int:
    rows = await conn.fetch(
        """SELECT s.id,s.storage_key,s.thumb_key,s.duplicate_of_id,e.department_id,s.taken_at,s.employee_id
           FROM screenshots s LEFT JOIN employees e ON e.id=s.employee_id ORDER BY (s.duplicate_of_id IS NULL),s.taken_at LIMIT 2000"""
    )
    now = datetime.now(UTC); expired = []
    for row in rows:
        days = await _effective_days(conn, "screenshots", row["employee_id"], row["department_id"])
        if row["taken_at"] < now - timedelta(days=days): expired.append(row)
    if not expired: return 0
    duplicate_ids = [row["id"] for row in expired if row["duplicate_of_id"] is not None]
    if duplicate_ids: await conn.execute("DELETE FROM screenshots WHERE id=ANY($1::bigint[])", duplicate_ids)
    storage = ObjectStorage(); removed = len(duplicate_ids)
    for row in [item for item in expired if item["duplicate_of_id"] is None]:
        if await conn.fetchval("SELECT EXISTS(SELECT 1 FROM screenshots WHERE duplicate_of_id=$1)", row["id"]): continue
        for key in {row["storage_key"], row["thumb_key"]} - {None}:
            try: await storage.remove(key)
            except Exception: pass
        await conn.execute("DELETE FROM screenshots WHERE id=$1", row["id"]); removed += 1
    return removed


async def purge_events(conn) -> int:
    rows = await conn.fetch("""SELECT e.id,e.department_id FROM employees e WHERE e.status IN ('active','inactive')""")
    removed = 0
    for employee in rows:
        days = await _effective_days(conn, "events", employee["id"], employee["department_id"])
        result = await conn.execute(
            """DELETE FROM activity_events a
               WHERE a.employee_id=$1 AND a.ts_end<now()-($2*interval '1 day')
                 AND NOT EXISTS(
                   SELECT 1 FROM screenshots s WHERE s.activity_event_id=a.id
                 )""",
            employee["id"],
            days,
        )
        removed += int(result.rsplit(" ", 1)[-1])
    return removed


async def purge_video_files(conn) -> int:
    root = Path(get_settings().video_recording_root).resolve()
    if not root.exists() or not root.is_dir(): return 0
    sessions = await conn.fetch("""SELECT DISTINCT ON(stream_key) stream_key,employee_id,e.department_id
                                  FROM stream_sessions s LEFT JOIN employees e ON e.id=s.employee_id
                                  ORDER BY stream_key,started_at DESC""")
    mapping = {row["stream_key"]: row for row in sessions}; removed = 0; now = datetime.now(UTC)
    storage = ObjectStorage()
    for stream_directory in root.iterdir():
        if not stream_directory.is_dir() or stream_directory.name not in mapping: continue
        row = mapping[stream_directory.name]; days = await _effective_days(conn, "video", row["employee_id"], row["department_id"])
        cutoff = now - timedelta(days=days)
        for file in stream_directory.rglob("*"):
            if not file.is_file(): continue
            resolved = file.resolve()
            if root not in resolved.parents: continue
            file_time = datetime.fromtimestamp(file.stat().st_mtime, UTC)
            if file_time >= cutoff: continue
            pinned = await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pinned_video_ranges WHERE employee_id=$1
                                           AND range_start<=$2+interval '5 minutes' AND range_end>=$2-interval '5 minutes')""",
                                         row["employee_id"], file_time)
            if not pinned:
                key = f"video/{resolved.relative_to(root).as_posix()}"
                try: await storage.remove(key)
                except Exception: continue
                try:
                    file.unlink(); removed += 1
                    await conn.execute("DELETE FROM stream_segments WHERE storage_key=$1", key)
                except OSError: pass
    return removed


async def purge_storage_pressure(conn) -> int:
    settings = get_settings(); root = Path(settings.video_recording_root).resolve()
    if not root.is_dir(): return 0
    usage = shutil.disk_usage(root); threshold = max(50, min(95, settings.storage_high_watermark_percent))
    used_percent = (usage.used / usage.total * 100) if usage.total else 0
    if used_percent <= threshold: return 0
    target_free = int(usage.total * (100 - threshold) / 100); need_free = max(0, target_free - usage.free)
    sessions = await conn.fetch("SELECT stream_key,employee_id FROM stream_sessions")
    mapping = {row["stream_key"]: row["employee_id"] for row in sessions}; candidates = []
    for directory in root.iterdir():
        if not directory.is_dir() or directory.name not in mapping: continue
        for path in directory.rglob("*.mp4"):
            if path.is_file(): candidates.append((path.stat().st_mtime, path, mapping[directory.name]))
    candidates.sort(key=lambda item: item[0]); storage = ObjectStorage(); removed = 0; freed = 0
    for modified, path, employee_id in candidates:
        instant = datetime.fromtimestamp(modified, UTC)
        pinned = await conn.fetchval("""SELECT EXISTS(SELECT 1 FROM pinned_video_ranges WHERE employee_id=$1
                                      AND range_start<=$2+interval '5 minutes' AND range_end>=$2-interval '5 minutes')""", employee_id, instant)
        if pinned: continue
        resolved = path.resolve()
        if root not in resolved.parents: continue
        size = path.stat().st_size; key = f"video/{resolved.relative_to(root).as_posix()}"
        try: await storage.remove(key)
        except Exception: continue
        try: path.unlink()
        except OSError: continue
        await conn.execute("DELETE FROM stream_segments WHERE storage_key=$1", key)
        removed += 1; freed += size
        if freed >= need_free: break
    details = {"threshold_percent": threshold, "used_percent": round(used_percent, 2), "removed": removed, "freed_bytes": freed}
    await conn.execute("""INSERT INTO audit_log(action,object_type,object_id,details_json)
                          VALUES('storage_pressure_cleanup','system','video-storage',$1::jsonb)""", json.dumps(details))
    await conn.execute("""INSERT INTO notifications(user_id,notification_type,payload_json)
                          SELECT id,'storage_pressure',$1::jsonb FROM users WHERE role_code IN ('admin','superadmin') AND is_active=true""", json.dumps(details))
    return removed


async def run_retention_once() -> dict[str, int]:
    async with connection() as conn:
        result = {"screenshots": await purge_screenshots(conn), "events": await purge_events(conn), "video": await purge_video_files(conn)}
        result["video_pressure"] = await purge_storage_pressure(conn)
        await conn.execute("""INSERT INTO audit_log(action,object_type,object_id,details_json)
                              VALUES('retention_completed','system','retention',$1::jsonb)""", __import__("json").dumps(result))
        return result
    return {"screenshots": 0, "events": 0, "video": 0, "video_pressure": 0}


async def retention_worker() -> None:
    while True:
        try: await run_retention_once()
        except asyncio.CancelledError: raise
        except Exception: pass
        await asyncio.sleep(6 * 60 * 60)
