"""Automatic stream recording policies for always-on, scheduled and trigger modes."""

import asyncio
import json
import secrets
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import asyncpg

from .config import get_settings
from .database import connection


def _local_now(now: datetime, timezone: str) -> datetime:
    try:
        return now.astimezone(ZoneInfo(timezone))
    except ZoneInfoNotFoundError:
        return now.astimezone(UTC)


def scheduled_now(windows: list[dict], now: datetime, timezone: str) -> bool:
    local = _local_now(now, timezone)
    for window in windows:
        try:
            weekdays = {int(value) for value in window.get("weekdays", [])}
            start = time.fromisoformat(str(window["start"])); end = time.fromisoformat(str(window["end"]))
            for day_offset in (0, -1):
                candidate_date = (local + timedelta(days=day_offset)).date()
                start_dt = datetime.combine(candidate_date, start, local.tzinfo)
                end_dt = datetime.combine(candidate_date, end, local.tzinfo)
                if end_dt <= start_dt: end_dt += timedelta(days=1)
                if start_dt.isoweekday() in weekdays and start_dt <= local <= end_dt: return True
        except (KeyError, TypeError, ValueError):
            continue
    return False


def within_work_schedule(rule: dict | None, now: datetime, timezone: str, grace_minutes: int = 60, holiday: bool = False) -> bool:
    if rule is None: return True
    if holiday: return False
    local = _local_now(now, timezone)
    try:
        weekdays = {int(value) for value in rule.get("weekdays", [])}
        start = time.fromisoformat(str(rule["start"])); end = time.fromisoformat(str(rule["end"]))
        grace = timedelta(minutes=max(0, grace_minutes))
        for day_offset in (0, -1):
            candidate_date = (local + timedelta(days=day_offset)).date()
            start_dt = datetime.combine(candidate_date, start, local.tzinfo)
            end_dt = datetime.combine(candidate_date, end, local.tzinfo)
            if end_dt <= start_dt: end_dt += timedelta(days=1)
            if start_dt.isoweekday() in weekdays and start_dt - grace <= local <= end_dt + grace: return True
        return False
    except (KeyError, TypeError, ValueError):
        return True


async def _resolved_config(conn: asyncpg.Connection, employee_id, department_id) -> dict:
    value = await conn.fetchval("SELECT value_json FROM settings WHERE key='agent.default'") or {}
    result = dict(value)
    rows = await conn.fetch(
        """SELECT value_json FROM scoped_settings WHERE key='agent' AND
           ((scope_type='department' AND scope_id=$1) OR (scope_type='employee' AND scope_id=$2))
           ORDER BY CASE scope_type WHEN 'department' THEN 1 ELSE 2 END""", department_id, employee_id,
    )
    for row in rows: result.update(row["value_json"])
    return result


async def run_stream_policy_once(now: datetime | None = None) -> None:
    now = now or datetime.now(UTC); settings = get_settings()
    async for conn in connection():
        devices = await conn.fetch(
            """SELECT d.id,d.employee_id,d.last_seen,d.last_activity_state,e.department_id,e.timezone,
                      (SELECT s.rules_json FROM schedule_assignments sa JOIN schedules s ON s.id=sa.schedule_id
                       WHERE sa.employee_id=e.id AND sa.valid_from<=current_date AND (sa.valid_to IS NULL OR sa.valid_to>=current_date)
                       ORDER BY sa.valid_from DESC LIMIT 1) AS work_schedule,
                      EXISTS(SELECT 1 FROM holidays h WHERE h.holiday_date=current_date AND h.kind='holiday') AS is_holiday
               FROM devices d JOIN employees e ON e.id=d.employee_id
               WHERE d.is_approved=true AND d.last_seen>now()-interval '90 seconds'"""
        )
        for device in devices:
            config = await _resolved_config(conn, device["employee_id"], device["department_id"])
            mode = str(config.get("video_recording_mode", "on_demand")); profile = str(config.get("video_profile", "medium"))
            allowed_by_schedule = within_work_schedule(device["work_schedule"], now, device["timezone"], int(config.get("schedule_grace_minutes", 60)), device["is_holiday"])
            active = await conn.fetchrow(
                """SELECT * FROM stream_sessions WHERE employee_id=$1 AND status IN ('requested','starting','live')
                   ORDER BY started_at DESC LIMIT 1""", device["employee_id"],
            )
            allowed = allowed_by_schedule and device["last_activity_state"] not in {"BREAK", "LOCKED"}
            should_start = mode == "always_on" and allowed
            if mode == "scheduled": should_start = allowed and scheduled_now(config.get("video_schedule_windows", []), now, device["timezone"])
            if mode == "trigger" and allowed and device["last_activity_state"] == "UNPRODUCTIVE":
                threshold = int(config.get("video_trigger_minutes", 5))
                should_start = bool(await conn.fetchval(
                    """SELECT EXISTS(SELECT 1 FROM activity_events WHERE device_id=$1 AND state='UNPRODUCTIVE'
                       AND ts_start<=now()-($2::int * interval '1 minute') AND ts_end>now()-interval '10 minutes')""",
                    device["id"], threshold,
                ))
            if active and active["mode"] == "on_demand":
                timeout = int(config.get("video_on_demand_timeout_minutes", 30))
                if (now - active["started_at"]).total_seconds() >= timeout * 60: should_start = False
                else: continue
            if active and (not should_start or active["mode"] != mode):
                await conn.execute("INSERT INTO agent_commands(device_id,command,payload_json) VALUES($1,'stop_stream',$2::jsonb)", device["id"], json.dumps({"session_id": str(active["id"])}))
                await conn.execute("UPDATE stream_sessions SET status='ended',ended_at=now() WHERE id=$1", active["id"])
                await conn.execute("INSERT INTO audit_log(action,object_type,object_id,target_employee_id,details_json) VALUES('stream_policy_stopped','stream',$1,$2,$3::jsonb)", str(active["id"]), device["employee_id"], json.dumps({"mode": mode}))
                active = None
            if should_start and active is None:
                stream_key = f"wm-{secrets.token_urlsafe(24)}"
                row = await conn.fetchrow(
                    """INSERT INTO stream_sessions(device_id,employee_id,profile,status,mode,stream_key,storage_prefix)
                       VALUES($1,$2,$3,'requested',$4,$5,$5) RETURNING id""",
                    device["id"], device["employee_id"], profile, mode, stream_key,
                )
                payload = {"session_id": str(row["id"]), "publish_url": f"{settings.mediamtx_publish_url.rstrip('/')}/{stream_key}/whip", "rtsp_url": f"{settings.mediamtx_rtsp_publish_url.rstrip('/')}/{stream_key}", "stream_key": stream_key, "profile": profile}
                await conn.execute("INSERT INTO agent_commands(device_id,command,payload_json) VALUES($1,'start_stream',$2::jsonb)", device["id"], json.dumps(payload))
                await conn.execute("INSERT INTO audit_log(action,object_type,object_id,target_employee_id,details_json) VALUES('stream_policy_started','stream',$1,$2,$3::jsonb)", str(row["id"]), device["employee_id"], json.dumps({"mode": mode, "profile": profile}))


async def stream_policy_worker() -> None:
    while True:
        try: await run_stream_policy_once()
        except Exception: pass
        await asyncio.sleep(30)
