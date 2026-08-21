import asyncio
import json
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import asyncpg

from .database import connection


def shift_bounds(day: date, rules: dict, timezone: str) -> tuple[datetime, datetime] | None:
    if day.isoweekday() not in rules.get("weekdays", []):
        return None
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        zone = UTC
    try:
        start_time = time.fromisoformat(rules["start"])
        end_time = time.fromisoformat(rules["end"])
    except (KeyError, ValueError, TypeError):
        return None
    start = datetime.combine(day, start_time, zone)
    end = datetime.combine(day, end_time, zone)
    if end <= start:
        end += timedelta(days=1)
    return start.astimezone(UTC), end.astimezone(UTC)


async def _absence_type_id(conn: asyncpg.Connection, code: str) -> int:
    return await conn.fetchval("SELECT id FROM absence_types WHERE code=$1", code)


async def _create_auto_absence(
    conn: asyncpg.Connection,
    employee_id,
    type_code: str,
    day: date,
    minutes: int | None,
    reason: str,
) -> bool:
    type_id = await _absence_type_id(conn, type_code)
    if type_id is None:
        return False
    inserted = await conn.fetchval(
        """
        INSERT INTO absences(employee_id,type_id,date_from,date_to,minutes,reason,status,is_auto)
        SELECT $1,$2,$3,$3,$4,$5,'draft',true
        WHERE NOT EXISTS(
            SELECT 1 FROM absences WHERE employee_id=$1 AND type_id=$2 AND date_from=$3 AND is_auto=true
        ) RETURNING id
        """,
        employee_id, type_id, day, minutes, reason,
    )
    if inserted is None:
        return False
    await conn.execute(
        """INSERT INTO notifications(user_id,notification_type,payload_json)
           SELECT u.id,'discipline_auto_event',jsonb_build_object(
               'absence_id',$1,'employee_id',$2,'type',$3,'date',$4::text)
           FROM users u WHERE u.role_code IN ('manager','admin','superadmin') AND u.is_active=true""",
        inserted, employee_id, type_code, day,
    )
    await conn.execute(
        """INSERT INTO audit_log(action,object_type,object_id,target_employee_id,details_json)
           VALUES('discipline_auto_detected','absence',$1,$2,$3::jsonb)""",
        str(inserted), employee_id, json.dumps({"type": type_code, "date": str(day), "minutes": minutes}),
    )
    return True


async def detect_discipline_for_day(conn: asyncpg.Connection, day: date, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    employees = await conn.fetch(
        """
        SELECT e.id,e.timezone,s.rules_json
        FROM employees e
        LEFT JOIN LATERAL (
            SELECT sch.rules_json FROM schedule_assignments sa JOIN schedules sch ON sch.id=sa.schedule_id
            WHERE sa.employee_id=e.id AND sa.valid_from<=$1 AND (sa.valid_to IS NULL OR sa.valid_to>=$1)
            ORDER BY sa.valid_from DESC LIMIT 1
        ) s ON true
        WHERE e.status='active'
        """, day,
    )
    default_rules = await conn.fetchval("SELECT rules_json FROM schedules WHERE name='Стандартный 5/2'") or {}
    created = 0
    for employee in employees:
        rules = employee["rules_json"] or default_rules
        bounds = shift_bounds(day, rules, employee["timezone"])
        if bounds is None:
            continue
        shift_start, shift_end = bounds
        tolerance = int(rules.get("late_tolerance_minutes", 5))
        if now < shift_end + timedelta(minutes=tolerance):
            continue
        approved_absence = await conn.fetchval(
            """SELECT EXISTS(SELECT 1 FROM absences a JOIN absence_types t ON t.id=a.type_id
               WHERE a.employee_id=$1 AND a.status='approved' AND t.effect='excludes_day'
                 AND a.date_from<=$2 AND a.date_to>=$2)""", employee["id"], day,
        )
        activity = await conn.fetchrow(
            """SELECT min(ts_start) AS first_at,max(ts_end) AS last_at,count(*)::int AS events
               FROM activity_events WHERE employee_id=$1 AND ts_start<$3 AND ts_end>$2
                 AND state IN ('PRODUCTIVE','NEUTRAL','UNPRODUCTIVE')""",
            employee["id"], shift_start, shift_end,
        )
        if not activity["events"]:
            if not approved_absence and await _create_auto_absence(
                conn, employee["id"], "ABSENCE_UNEXCUSED", day, None,
                "Автодетект: нет активности за всю смену",
            ):
                created += 1
            continue
        late_minutes = max(0, int((activity["first_at"] - shift_start).total_seconds() // 60))
        if late_minutes > tolerance and await _create_auto_absence(
            conn, employee["id"], "LATE_INVALID", day, late_minutes,
            "Автодетект: требуется уточнить уважительность опоздания",
        ):
            created += 1
        early_minutes = max(0, int((shift_end - activity["last_at"]).total_seconds() // 60))
        if early_minutes > tolerance and await _create_auto_absence(
            conn, employee["id"], "EARLY_LEAVE", day, early_minutes,
            "Автодетект: раннее завершение активности",
        ):
            created += 1
    return created


async def discipline_worker() -> None:
    while True:
        try:
            async with connection() as conn:
                today = datetime.now(UTC).date()
                await detect_discipline_for_day(conn, today - timedelta(days=1))
                await detect_discipline_for_day(conn, today)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The next run retries; application availability must not depend on the worker.
            pass
        await asyncio.sleep(15 * 60)
