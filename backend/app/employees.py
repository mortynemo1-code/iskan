import io
import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from .analytics import build_productivity_report, db, validate_range
from .analytics_calculations import percentage
from .analytics_schemas import TrendPoint
from .auth import CurrentUser, require_permission, visible_employee_ids
from .employee_schemas import (
    ApplicationUsage,
    EmployeeAbsenceSummary,
    EmployeeDevice,
    EmployeeOverview,
    RecentActivity,
)
from .config import get_settings
from .storage import ObjectStorage


router = APIRouter(prefix="/api/v1/employees", tags=["employees"])


async def ensure_visible(conn: asyncpg.Connection, user: CurrentUser, employee_id: UUID) -> None:
    visible = await visible_employee_ids(conn, user)
    if visible is not None and employee_id not in visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode()


@router.post("/{employee_id}/export")
async def export_employee_data(
    employee_id: UUID,
    request: Request,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("settings:manage")),
) -> StreamingResponse:
    employee = await conn.fetchrow("SELECT * FROM employees WHERE id=$1", employee_id)
    if employee is None: raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    datasets = {
        "employee.json": dict(employee),
        "devices.json": [dict(row) for row in await conn.fetch("SELECT id,hostname,machine_guid,os_version,agent_version,last_seen FROM devices WHERE employee_id=$1", employee_id)],
        "activity.json": [dict(row) for row in await conn.fetch("SELECT * FROM activity_events WHERE employee_id=$1 ORDER BY ts_start", employee_id)],
        "absences.json": [dict(row) for row in await conn.fetch("SELECT a.*,t.code AS type_code,t.name AS type_name FROM absences a JOIN absence_types t ON t.id=a.type_id WHERE a.employee_id=$1 ORDER BY date_from", employee_id)],
        "screenshots.json": [dict(row) for row in await conn.fetch("SELECT * FROM screenshots WHERE employee_id=$1 ORDER BY taken_at", employee_id)],
        "stream_sessions.json": [dict(row) for row in await conn.fetch("SELECT * FROM stream_sessions WHERE employee_id=$1 ORDER BY started_at", employee_id)],
        "audit_access.json": [dict(row) for row in await conn.fetch("SELECT action,object_type,object_id,ip_address,user_agent,created_at,details_json FROM audit_log WHERE target_employee_id=$1 ORDER BY created_at", employee_id)],
    }
    screenshot_rows = await conn.fetch(
        """SELECT s.id,COALESCE(s.storage_key,source.storage_key) AS storage_key
           FROM screenshots s LEFT JOIN screenshots source ON source.id=s.duplicate_of_id
           WHERE s.employee_id=$1 ORDER BY s.taken_at""", employee_id,
    )
    spool = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
    storage = ObjectStorage()
    with zipfile.ZipFile(spool, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        archive.writestr("README.txt", "Выгрузка персональных данных Workforce Monitoring. Время указано в UTC/ISO 8601.\n")
        for filename, value in datasets.items(): archive.writestr(filename, _json_bytes(value))
        written: set[str] = set()
        for row in screenshot_rows:
            key = row["storage_key"]
            if not key or key in written: continue
            written.add(key)
            try: archive.writestr(f"screenshots/{row['id']}{Path(key).suffix}", await storage.get_bytes(key))
            except Exception: archive.writestr(f"screenshots/{row['id']}.missing.txt", f"Объект недоступен: {key}")
    spool.seek(0)
    ip = request.headers.get("x-forwarded-for", "").rsplit(",", 1)[-1].strip() or (request.client.host if request.client else None)
    await conn.execute(
        """INSERT INTO audit_log(user_id,action,object_type,object_id,target_employee_id,ip_address,user_agent,details_json)
           VALUES($1,'employee_data_exported','employee',$2,$3,$4::inet,$5,jsonb_build_object('activity_events',$6,'screenshots',$7))""",
        user.id, str(employee_id), employee_id, ip, request.headers.get("user-agent"), len(datasets["activity.json"]), len(screenshot_rows),
    )
    headers = {"Content-Disposition": f'attachment; filename="employee-{employee_id}.zip"'}
    return StreamingResponse(spool, media_type="application/zip", headers=headers)


@router.delete("/{employee_id}/data", status_code=200)
async def delete_employee_data(
    employee_id: UUID,
    request: Request,
    confirm: str = Query(),
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("settings:manage")),
) -> dict[str, object]:
    if confirm != str(employee_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Для подтверждения передайте UUID сотрудника в параметре confirm")
    employee = await conn.fetchrow("SELECT id,full_name FROM employees WHERE id=$1", employee_id)
    if employee is None: raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    object_keys = await conn.fetch(
        """SELECT storage_key AS key FROM screenshots WHERE employee_id=$1 AND storage_key IS NOT NULL
           UNION SELECT thumb_key FROM screenshots WHERE employee_id=$1 AND thumb_key IS NOT NULL
           UNION SELECT attachment_key FROM absences WHERE employee_id=$1 AND attachment_key IS NOT NULL
           UNION SELECT ss.storage_key FROM stream_segments ss JOIN stream_sessions s ON s.id=ss.session_id WHERE s.employee_id=$1""",
        employee_id,
    )
    storage = ObjectStorage()
    for row in object_keys:
        await storage.remove(row["key"])
    video_root = Path(get_settings().video_recording_root).resolve()
    stream_keys = await conn.fetch("SELECT stream_key FROM stream_sessions WHERE employee_id=$1", employee_id)
    for row in stream_keys:
        candidate = (video_root / row["stream_key"]).resolve()
        if video_root in candidate.parents and candidate.is_dir(): shutil.rmtree(candidate)
    async with conn.transaction():
        counts = {
            "screenshots": await conn.fetchval("WITH deleted AS (DELETE FROM screenshots WHERE employee_id=$1 RETURNING 1) SELECT count(*) FROM deleted", employee_id),
            "events": await conn.fetchval("WITH deleted AS (DELETE FROM activity_events WHERE employee_id=$1 RETURNING 1) SELECT count(*) FROM deleted", employee_id),
            "absences": await conn.fetchval("WITH deleted AS (DELETE FROM absences WHERE employee_id=$1 RETURNING 1) SELECT count(*) FROM deleted", employee_id),
            "streams": await conn.fetchval("WITH deleted AS (DELETE FROM stream_sessions WHERE employee_id=$1 RETURNING 1) SELECT count(*) FROM deleted", employee_id),
        }
        await conn.execute("DELETE FROM pinned_video_ranges WHERE employee_id=$1", employee_id)
        await conn.execute("UPDATE windows_accounts SET employee_id=NULL WHERE employee_id=$1", employee_id)
        await conn.execute("UPDATE devices SET employee_id=NULL,is_approved=false WHERE employee_id=$1", employee_id)
        ip = request.headers.get("x-forwarded-for", "").rsplit(",", 1)[-1].strip() or (request.client.host if request.client else None)
        await conn.execute(
            """INSERT INTO audit_log(user_id,action,object_type,object_id,target_employee_id,ip_address,user_agent,details_json)
               VALUES($1,'employee_data_deleted','employee',$2,$3,$4::inet,$5,$6::jsonb)""",
            user.id, str(employee_id), employee_id, ip, request.headers.get("user-agent"), json.dumps(counts),
        )
    return {"deleted": True, "employee_id": str(employee_id), "counts": counts}


@router.get("/{employee_id}/overview", response_model=EmployeeOverview)
async def employee_overview(
    employee_id: UUID,
    range_start: datetime = Query(alias="from"),
    range_end: datetime = Query(alias="to"),
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("timeline:view")),
) -> EmployeeOverview:
    validate_range(range_start, range_end)
    await ensure_visible(conn, user, employee_id)
    employee = await conn.fetchrow(
        """
        SELECT e.id, e.full_name, e.email, e.department_id,
               COALESCE(d.name, e.department_name) AS department_name,
               e.position_title, e.hire_date, e.timezone, e.status, e.planned_daily_minutes
        FROM employees e LEFT JOIN departments d ON d.id=e.department_id
        WHERE e.id=$1
        """,
        employee_id,
    )
    if employee is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    report = await build_productivity_report(
        conn, user, range_start, range_end, "active", None, employee_id, "employee", "asc"
    )
    if not report.rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    metrics = report.rows[0]

    app_rows = await conn.fetch(
        """
        SELECT CASE WHEN a.url_domain IS NOT NULL AND a.url_domain<>'' THEN a.url_domain
                    ELSE COALESCE(a.app_name, a.process_name, 'Неизвестно') END AS usage_key,
               CASE WHEN a.url_domain IS NOT NULL AND a.url_domain<>'' THEN 'site' ELSE 'application' END AS kind,
               max(COALESCE(a.app_name, a.process_name, a.url_domain, 'Неизвестно')) AS label,
               a.category_id, max(c.name) AS category_name,
               COALESCE(max(c.productivity), max(a.state), 'NEUTRAL') AS productivity,
               sum(EXTRACT(EPOCH FROM (LEAST(a.ts_end, $3) - GREATEST(a.ts_start, $2))))::bigint AS seconds
        FROM activity_events a LEFT JOIN categories c ON c.id=a.category_id
        WHERE a.employee_id=$1 AND a.ts_start<$3 AND a.ts_end>$2
          AND a.state IN ('PRODUCTIVE','NEUTRAL','UNPRODUCTIVE')
        GROUP BY usage_key, kind, a.category_id
        ORDER BY seconds DESC LIMIT 20
        """,
        employee_id,
        range_start,
        range_end,
    )
    active_seconds = sum(int(row["seconds"]) for row in app_rows)
    applications = [
        ApplicationUsage(
            key=row["usage_key"],
            label=row["label"],
            kind=row["kind"],
            category_id=row["category_id"],
            category_name=row["category_name"],
            productivity=row["productivity"],
            seconds=int(row["seconds"]),
            percent=percentage(int(row["seconds"]), active_seconds),
        )
        for row in app_rows
    ]
    trend_rows = await conn.fetch(
        """
        SELECT (ts_start AT TIME ZONE $4)::date AS day,
               COALESCE(sum(duration_sec) FILTER (WHERE state='PRODUCTIVE'), 0)::bigint AS productive_seconds,
               COALESCE(sum(duration_sec) FILTER (WHERE state IN ('PRODUCTIVE','NEUTRAL','UNPRODUCTIVE')), 0)::bigint AS active_seconds
        FROM activity_events
        WHERE employee_id=$1 AND ts_start<$3 AND ts_end>$2
        GROUP BY day ORDER BY day
        """,
        employee_id,
        range_start,
        range_end,
        employee["timezone"],
    )
    trend = [
        TrendPoint(
            day=row["day"],
            productive_seconds=int(row["productive_seconds"]),
            active_seconds=int(row["active_seconds"]),
            productive_percent=percentage(int(row["productive_seconds"]), int(row["active_seconds"])),
        )
        for row in trend_rows
    ]
    device_rows = await conn.fetch(
        """
        SELECT id, hostname, os_version, agent_version, is_approved, last_seen, last_activity_state
        FROM devices WHERE employee_id=$1 ORDER BY last_seen DESC NULLS LAST
        """,
        employee_id,
    )
    absence = await conn.fetchrow(
        """
        SELECT COALESCE(sum((a.date_to - a.date_from) + 1)
                   FILTER (WHERE a.status='approved' AND t.effect='excludes_day'), 0)::int AS approved_days,
               count(*) FILTER (WHERE a.status IN ('draft','pending'))::int AS pending_requests,
               count(*) FILTER (WHERE a.status='approved' AND t.effect='counts_as_violation')::int AS violations,
               COALESCE(sum(a.minutes) FILTER (WHERE a.status='approved' AND t.code LIKE 'LATE_%'), 0)::int AS late_minutes
        FROM absences a JOIN absence_types t ON t.id=a.type_id
        WHERE a.employee_id=$1 AND a.date_from<=$3::date AND a.date_to>=$2::date
        """,
        employee_id,
        range_start,
        range_end,
    )
    activity_rows = await conn.fetch(
        """
        SELECT a.event_uuid, a.ts_start, a.ts_end, a.duration_sec, a.state,
               a.app_name, a.process_name, a.window_title, a.url_domain, a.url_path,
               a.category_id, c.name AS category_name,
               (SELECT s.id FROM screenshots s WHERE s.activity_event_id=a.id ORDER BY s.taken_at LIMIT 1) AS screenshot_id
        FROM activity_events a LEFT JOIN categories c ON c.id=a.category_id
        WHERE a.employee_id=$1 AND a.ts_start<$3 AND a.ts_end>$2
        ORDER BY a.ts_start DESC LIMIT 100
        """,
        employee_id,
        range_start,
        range_end,
    )
    return EmployeeOverview(
        **dict(employee),
        metrics=metrics,
        trend=trend,
        applications=applications,
        devices=[EmployeeDevice(**dict(row)) for row in device_rows],
        absence_summary=EmployeeAbsenceSummary(**dict(absence)),
        recent_activity=[RecentActivity(**dict(row)) for row in activity_rows],
    )
