import asyncio
import hashlib
import json
import secrets
import re
import shutil
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response as FastAPIResponse
from fastapi.openapi.docs import get_swagger_ui_html
from redis.asyncio import Redis

from .admin import router as admin_router
from .analytics import router as analytics_router
from .employees import router as employees_router
from .screenshots import router as screenshots_router
from .streams import router as streams_router
from .absences import router as absences_router
from .reports import router as reports_router
from .settings_api import router as settings_router
from .middleware import GzipRequestMiddleware, protection_middleware
from .auth import (
    ACCESS_COOKIE,
    CurrentUser,
    admin_router as users_admin_router,
    authenticate_access_token,
    ensure_bootstrap_admin,
    require_permission,
    router as auth_router,
    visible_employee_ids,
)
from .config import Settings, get_settings
from .database import connect_database, connection, disconnect_database
from .activity import clipped_duration, validate_interval
from .presence import calculate_presence, normalize_activity_state
from .rules_engine import ClassificationRule, classify_result
from .discipline import discipline_worker
from .report_jobs import report_schedule_worker
from .retention_jobs import retention_worker
from .reclassification_jobs import reclassification_worker
from .storage import ObjectStorage
from .upload_validation import has_valid_signature
from .schemas import (
    AgentConfig,
    AgentSystemEventRequest,
    ActivityBatchRequest,
    ActivityBatchResponse,
    EmployeeTimeline,
    HeartbeatRequest,
    HeartbeatResponse,
    PresenceItem,
    RegisterRequest,
    RegisterResponse,
    TimelineResponse,
    TimelineSegment,
    TimelineTotals,
)

redis_client: Redis | None = None


def hash_device_token(token: str, pepper: str) -> str:
    return hashlib.sha256(f"{pepper}:{token}".encode()).hexdigest()


@asynccontextmanager
async def lifespan(_: FastAPI):
    global redis_client
    get_settings().validate_runtime()
    await connect_database()
    await ensure_bootstrap_admin(get_settings())
    redis_client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    await redis_client.ping()
    workers = []
    if get_settings().run_background_workers:
        workers = [
            asyncio.create_task(discipline_worker()),
            asyncio.create_task(report_schedule_worker()),
            asyncio.create_task(retention_worker()),
            asyncio.create_task(reclassification_worker()),
        ]
    yield
    for worker in workers:
        worker.cancel()
    for worker in workers:
        try:
            await worker
        except asyncio.CancelledError:
            pass
    await redis_client.aclose()
    redis_client = None
    await disconnect_database()


app = FastAPI(
    title="Workforce Monitoring API",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(GzipRequestMiddleware)


@app.middleware("http")
async def protect_requests(request: Request, call_next):
    return await protection_middleware(request, call_next, lambda: redis_client)


@app.exception_handler(HTTPException)
async def problem_http_exception(request: Request, error: HTTPException) -> JSONResponse:
    detail = error.detail if isinstance(error.detail, str) else json.dumps(error.detail, ensure_ascii=False)
    return JSONResponse(
        {"type": "about:blank", "title": "Request failed",
         "status": error.status_code, "detail": detail, "instance": request.url.path},
        status_code=error.status_code, headers=error.headers, media_type="application/problem+json",
    )


@app.exception_handler(RequestValidationError)
async def problem_validation_exception(request: Request, error: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        {"type": "about:blank", "title": "Validation Error", "status": 422,
         "detail": "Проверьте параметры запроса", "instance": request.url.path, "errors": error.errors()},
        status_code=422, media_type="application/problem+json",
    )
app.include_router(auth_router)
app.include_router(users_admin_router)
app.include_router(admin_router)
app.include_router(analytics_router)
app.include_router(employees_router)
app.include_router(screenshots_router)
app.include_router(streams_router)
app.include_router(absences_router)
app.include_router(reports_router)
app.include_router(settings_router)


async def db() -> asyncpg.Connection:
    async for conn in connection():
        yield conn


async def authenticated_device(
    authorization: str | None = Header(default=None),
    conn: asyncpg.Connection = Depends(db),
    settings: Settings = Depends(get_settings),
) -> asyncpg.Record:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Device token is required")
    token_hash = hash_device_token(authorization[7:], settings.device_token_pepper)
    device = await conn.fetchrow("SELECT * FROM devices WHERE token_hash = $1", token_hash)
    if device is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid device token")
    return device


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/ready", include_in_schema=False)
async def ready(conn: asyncpg.Connection = Depends(db)) -> dict[str, str]:
    await conn.fetchval("SELECT 1")
    if redis_client is None or not await redis_client.ping():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Redis is unavailable")
    return {"status": "ready", "postgres": "ok", "redis": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics(conn: asyncpg.Connection = Depends(db)) -> PlainTextResponse:
    settings = get_settings()
    values = await conn.fetchrow(
        """SELECT
          (SELECT count(*) FROM devices WHERE is_approved=true AND last_seen>=now()-($1*interval '1 second')) AS online,
          (SELECT count(*) FROM devices WHERE is_approved=true) AS approved,
          (SELECT count(*) FROM activity_events WHERE created_at>=now()-interval '1 minute') AS events_minute,
          (SELECT count(*) FROM agent_commands WHERE status='pending') AS pending_commands,
          (SELECT count(*) FROM report_runs WHERE status='failed' AND created_at>=now()-interval '1 day') AS failed_reports,
          (SELECT count(*) FROM stream_sessions WHERE status='live') AS live_streams,
          (SELECT count(*) FROM activity_events) AS events_total,
          (SELECT count(*) FROM screenshots) AS screenshots_total,
          (SELECT COALESCE(sum(size_bytes),0) FROM screenshots WHERE duplicate_of_id IS NULL) AS screenshot_bytes,
          (SELECT COALESCE(sum(size_bytes),0) FROM stream_segments) AS stream_bytes""",
        settings.presence_ttl_seconds,
    )
    versions = await conn.fetch("SELECT agent_version,count(*)::int AS devices FROM devices GROUP BY agent_version ORDER BY agent_version")
    try: disk = shutil.disk_usage(settings.video_recording_root); free_percent = disk.free / disk.total * 100 if disk.total else 0
    except OSError: free_percent = 0
    lines = [
        "# HELP workforce_agents_online Approved agents seen inside the presence TTL.",
        "# TYPE workforce_agents_online gauge", f"workforce_agents_online {values['online']}",
        "# TYPE workforce_agents_approved gauge", f"workforce_agents_approved {values['approved']}",
        "# TYPE workforce_ingest_events_last_minute gauge", f"workforce_ingest_events_last_minute {values['events_minute']}",
        "# TYPE workforce_agent_commands_pending gauge", f"workforce_agent_commands_pending {values['pending_commands']}",
        "# TYPE workforce_report_failures_day gauge", f"workforce_report_failures_day {values['failed_reports']}",
        "# TYPE workforce_live_streams gauge", f"workforce_live_streams {values['live_streams']}",
        "# TYPE agents_online_total gauge", f"agents_online_total {values['online']}",
        "# TYPE agents_offline_total gauge", f"agents_offline_total {max(0, values['approved'] - values['online'])}",
        "# TYPE events_ingested_total counter", f"events_ingested_total {values['events_total']}",
        "# TYPE screenshots_uploaded_total counter", f"screenshots_uploaded_total {values['screenshots_total']}",
        "# TYPE screenshot_upload_bytes_total counter", f"screenshot_upload_bytes_total {values['screenshot_bytes']}",
        "# TYPE streams_active_total gauge", f"streams_active_total {values['live_streams']}",
        "# TYPE storage_used_bytes gauge", f'storage_used_bytes{{type="screenshots"}} {values["screenshot_bytes"]}', f'storage_used_bytes{{type="video"}} {values["stream_bytes"]}',
        "# TYPE storage_free_percent gauge", f"storage_free_percent {free_percent:.3f}",
        "# TYPE agent_version_info gauge",
    ]
    for row in versions:
        version = re.sub(r'[^0-9A-Za-z._+-]', '_', row['agent_version'])
        lines.append(f'agent_version_info{{version="{version}"}} {row["devices"]}')
    lines.append("")
    body = "\n".join(lines)
    return PlainTextResponse(body, media_type="text/plain; version=0.0.4")


@app.get("/api/openapi.json", include_in_schema=False)
async def protected_openapi(
    _: CurrentUser = Depends(require_permission("settings:manage")),
) -> JSONResponse:
    return JSONResponse(app.openapi())


@app.get("/api/docs", include_in_schema=False)
async def protected_docs(
    _: CurrentUser = Depends(require_permission("settings:manage")),
) -> Response:
    return get_swagger_ui_html(openapi_url="/api/openapi.json", title="Workforce Monitoring API")


@app.post("/api/v1/agent/register", response_model=RegisterResponse, status_code=201)
async def register_device(
    payload: RegisterRequest,
    conn: asyncpg.Connection = Depends(db),
    settings: Settings = Depends(get_settings),
) -> RegisterResponse:
    if not secrets.compare_digest(payload.installation_token, settings.installation_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid installation token")
    device_token = secrets.token_urlsafe(48)
    token_hash = hash_device_token(device_token, settings.device_token_pepper)
    row = await conn.fetchrow(
        """
        INSERT INTO devices(hostname, machine_guid, os_version, agent_version, token_hash)
        VALUES($1, $2, $3, $4, $5)
        ON CONFLICT(machine_guid) DO UPDATE SET
          hostname = EXCLUDED.hostname,
          os_version = EXCLUDED.os_version,
          agent_version = EXCLUDED.agent_version,
          token_hash = EXCLUDED.token_hash
        RETURNING id, is_approved
        """,
        payload.hostname,
        payload.machine_guid,
        payload.os_version,
        payload.agent_version,
        token_hash,
    )
    await conn.execute(
        "INSERT INTO audit_log(action, object_type, object_id) VALUES('device_registered', 'device', $1)",
        str(row["id"]),
    )
    return RegisterResponse(
        device_id=row["id"],
        device_token=device_token,
        heartbeat_interval_seconds=settings.heartbeat_interval_seconds,
        approval_required=not row["is_approved"],
    )


@app.post("/api/v1/agent/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    payload: HeartbeatRequest,
    device: asyncpg.Record = Depends(authenticated_device),
    conn: asyncpg.Connection = Depends(db),
    settings: Settings = Depends(get_settings),
) -> HeartbeatResponse:
    state = normalize_activity_state(payload.activity_state)
    now = datetime.now(UTC)
    await conn.execute(
        "UPDATE devices SET last_seen=$1, last_activity_state=$2, agent_version=$3 WHERE id=$4",
        now,
        state,
        payload.agent_version,
        device["id"],
    )
    if redis_client is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Presence storage unavailable")
    value = json.dumps({"state": state, "at": now.isoformat()})
    await redis_client.setex(f"presence:{device['id']}", settings.presence_ttl_seconds, value)
    await redis_client.publish("presence_updates", str(device["id"]))
    commands = await conn.fetch(
        """UPDATE agent_commands SET status='delivered',delivered_at=now()
           WHERE id IN (SELECT id FROM agent_commands WHERE device_id=$1 AND status='pending'
                        AND expires_at>now() ORDER BY requested_at LIMIT 20 FOR UPDATE SKIP LOCKED)
           RETURNING id,command,payload_json""",
        device["id"],
    )
    return HeartbeatResponse(
        server_time=now,
        next_heartbeat_seconds=settings.heartbeat_interval_seconds,
        commands=[{"id": str(row["id"]), "command": row["command"], "payload": row["payload_json"]} for row in commands],
    )


@app.get("/api/v1/agent/config", response_model=AgentConfig)
async def agent_config(
    if_none_match: str | None = Header(default=None),
    device: asyncpg.Record = Depends(authenticated_device),
    conn: asyncpg.Connection = Depends(db),
) -> Response:
    row = await conn.fetchrow("SELECT value_json FROM settings WHERE key='agent.default'")
    raw_config = row["value_json"] if row else {}
    if isinstance(raw_config, str):
        raw_config = json.loads(raw_config)
    employee_config = await conn.fetchrow(
        """
        SELECT e.timezone,e.id AS employee_id,e.department_id,
               (SELECT s.rules_json FROM schedule_assignments sa JOIN schedules s ON s.id=sa.schedule_id
                WHERE sa.employee_id=e.id AND sa.valid_from<=current_date
                  AND (sa.valid_to IS NULL OR sa.valid_to>=current_date)
                ORDER BY sa.valid_from DESC LIMIT 1) AS work_schedule
        FROM employees e WHERE e.id=$1
        """,
        device["employee_id"],
    ) if device["employee_id"] else None
    holidays = await conn.fetch(
        "SELECT holiday_date FROM holidays WHERE holiday_date BETWEEN current_date - 1 AND current_date + 45 AND kind='holiday'"
    )
    if employee_config:
        scoped_rows = await conn.fetch(
            """SELECT scope_type,value_json FROM scoped_settings WHERE key='agent' AND (
                 (scope_type='department' AND scope_id=$1) OR (scope_type='employee' AND scope_id=$2))
               ORDER BY CASE scope_type WHEN 'department' THEN 1 ELSE 2 END""",
            employee_config["department_id"], employee_config["employee_id"],
        )
        for scoped in scoped_rows:
            raw_config = {**raw_config, **scoped["value_json"]}
    raw_config = {
        **raw_config,
        "employee_timezone": employee_config["timezone"] if employee_config else "UTC",
        "work_schedule": employee_config["work_schedule"] if employee_config else None,
        "holiday_dates": [str(row["holiday_date"]) for row in holidays],
    }
    config = AgentConfig.model_validate(raw_config)
    payload = config.model_dump_json()
    etag = '"' + hashlib.sha256(payload.encode()).hexdigest() + '"'
    if if_none_match == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    return JSONResponse(content=config.model_dump(mode="json"), headers={"ETag": etag})


@app.post("/api/v1/agent/events", status_code=202)
async def receive_agent_system_event(
    payload: AgentSystemEventRequest,
    device: asyncpg.Record = Depends(authenticated_device),
    conn: asyncpg.Connection = Depends(db),
) -> dict[str, bool]:
    details = {
        **payload.details,
        "occurred_at": payload.occurred_at.isoformat(),
        "windows_session_id": payload.windows_session_id,
    }
    await conn.execute(
        """
        INSERT INTO audit_log(action, object_type, object_id, details_json)
        VALUES($1, 'device', $2, $3::jsonb)
        """,
        payload.code,
        str(device["id"]),
        json.dumps(details),
    )
    return {"accepted": True}


@app.post("/api/v1/agent/logs", status_code=201)
async def upload_agent_logs(
    archive: UploadFile = File(...),
    reason: str | None = Form(default=None),
    device: asyncpg.Record = Depends(authenticated_device),
    conn: asyncpg.Connection = Depends(db),
) -> dict[str, str]:
    content = await archive.read(20 * 1024 * 1024 + 1)
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Архив диагностики превышает 20 МБ")
    if not has_valid_signature("application/zip", content):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Ожидается ZIP-архив")
    diagnostic_id = secrets.token_hex(16)
    key = f"diagnostics/{device['id']}/{datetime.now(UTC):%Y/%m}/{diagnostic_id}.zip"
    await ObjectStorage().put_bytes(key, content, "application/zip")
    row_id = await conn.fetchval(
        """INSERT INTO agent_diagnostics(device_id,storage_key,size_bytes,reason)
           VALUES($1,$2,$3,$4) RETURNING id""",
        device["id"], key, len(content), (reason or "agent_command")[:200],
    )
    await conn.execute(
        "INSERT INTO audit_log(action,object_type,object_id,details_json) VALUES('agent_logs_uploaded','device',$1,jsonb_build_object('diagnostic_id',$2::text,'size_bytes',$3))",
        str(device["id"]), row_id, len(content),
    )
    return {"id": str(row_id)}


@app.get("/api/v1/agent/update")
async def agent_update_manifest(
    device: asyncpg.Record = Depends(authenticated_device),
    conn: asyncpg.Connection = Depends(db),
) -> dict[str, object]:
    row = await conn.fetchrow(
        """SELECT id,version,sha256,rollout_percent,maintenance_start_hour,maintenance_end_hour
           FROM update_releases WHERE is_active=true ORDER BY created_at DESC LIMIT 1"""
    )
    if row is None:
        return {"available": False}
    bucket = int(hashlib.sha256(str(device["id"]).encode()).hexdigest()[:8], 16) % 100
    if bucket >= row["rollout_percent"]:
        return {"available": False, "rollout_pending": True}
    return {
        "available": True,
        "id": str(row["id"]),
        "version": row["version"],
        "sha256": row["sha256"],
        "package_url": f"api/v1/agent/update/{row['id']}/package",
        "maintenance_start_hour": row["maintenance_start_hour"],
        "maintenance_end_hour": row["maintenance_end_hour"],
    }


@app.get("/api/v1/agent/update/{release_id}/package", response_class=FastAPIResponse)
async def download_agent_update(
    release_id: UUID,
    _: asyncpg.Record = Depends(authenticated_device),
    conn: asyncpg.Connection = Depends(db),
) -> FastAPIResponse:
    key = await conn.fetchval("SELECT storage_key FROM update_releases WHERE id=$1 AND is_active=true", release_id)
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Релиз не найден")
    content = await ObjectStorage().get_bytes(key)
    return FastAPIResponse(content, media_type="application/x-msi", headers={"Content-Disposition": "attachment; filename=workforce-agent.msi"})


@app.post("/api/v1/agent/activity/batch", response_model=ActivityBatchResponse, status_code=202)
async def receive_activity_batch(
    payload: ActivityBatchRequest,
    device: asyncpg.Record = Depends(authenticated_device),
    conn: asyncpg.Connection = Depends(db),
) -> ActivityBatchResponse:
    accepted = 0
    time_skew = abs((payload.sent_at - datetime.now(UTC)).total_seconds()) > 300
    rule_rows = await conn.fetch(
        """
        SELECT r.priority, r.match_field, r.match_type, r.pattern,
               c.productivity, c.id AS category_id
        FROM rules r
        JOIN categories c ON c.id = r.category_id
        WHERE r.enabled = true AND r.scope_type = 'global'
        ORDER BY r.priority
        """
    )
    rules = [ClassificationRule(**dict(row)) for row in rule_rows]
    async with conn.transaction():
        for event in payload.events:
            classification = classify_result(event, rules)
            interval = validate_interval(event.ts_start, event.ts_end, classification.state)
            event_employee_id = device["employee_id"]
            is_quarantined = False
            if event.windows_sid:
                account = await conn.fetchrow(
                    "SELECT id,employee_id FROM windows_accounts WHERE device_id=$1 AND sid=$2",
                    device["id"], event.windows_sid,
                )
                if account is None:
                    mapped_accounts = await conn.fetchval(
                        "SELECT count(*) FROM windows_accounts WHERE device_id=$1 AND employee_id IS NOT NULL",
                        device["id"],
                    )
                    initial_employee_id = device["employee_id"] if mapped_accounts == 0 else None
                    account = await conn.fetchrow(
                        """INSERT INTO windows_accounts(device_id,sid,username,employee_id)
                           VALUES($1,$2,$3,$4) ON CONFLICT(device_id,sid) DO UPDATE SET username=EXCLUDED.username
                           RETURNING id,employee_id""",
                        device["id"], event.windows_sid, event.windows_username or event.windows_sid, initial_employee_id,
                    )
                    if initial_employee_id is None:
                        await conn.execute(
                            """INSERT INTO audit_log(action,object_type,object_id,details_json)
                               VALUES('unknown_account','windows_account',$1,jsonb_build_object('device_id',$2::text,'username',$3))""",
                            str(account["id"]), device["id"], event.windows_username,
                        )
                        await conn.execute(
                            """INSERT INTO notifications(user_id,notification_type,payload_json)
                               SELECT id,'unknown_windows_account',jsonb_build_object('account_id',$1,'device_id',$2,'username',$3)
                               FROM users WHERE role_code IN ('admin','superadmin') AND is_active=true""",
                            account["id"], device["id"], event.windows_username,
                        )
                event_employee_id = account["employee_id"]
                is_quarantined = event_employee_id is None
            inserted = await conn.fetchval(
                """
                INSERT INTO activity_events(
                    event_uuid, device_id, employee_id, ts_start, ts_end, duration_sec,
                    state, process_name, app_name, window_title, url_domain, url_path,
                    windows_session_id, is_remote, keystrokes, clicks, mouse_distance,
                    category_id, windows_sid, windows_username, is_quarantined, time_skew
                )
                VALUES(
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9, $10, $11, $12,
                    $13, $14, $15, $16, $17, $18, $19, $20, $21, $22
                )
                ON CONFLICT(event_uuid) DO NOTHING
                RETURNING id
                """,
                event.event_uuid,
                device["id"],
                event_employee_id,
                interval.start,
                interval.end,
                interval.duration_seconds,
                interval.state,
                event.process_name,
                event.app_name,
                event.window_title,
                event.url_domain,
                event.url_path,
                event.windows_session_id,
                event.is_remote,
                event.keystrokes,
                event.clicks,
                event.mouse_distance,
                classification.category_id,
                event.windows_sid,
                event.windows_username,
                is_quarantined,
                time_skew,
            )
            accepted += int(inserted is not None)

        latest = max(payload.events, key=lambda item: item.ts_end)
        latest_state = classify_result(latest, rules).state
        await conn.execute(
            "UPDATE devices SET last_activity_state=$1 WHERE id=$2",
            latest_state,
            device["id"],
        )

    duplicates = len(payload.events) - accepted
    return ActivityBatchResponse(accepted=accepted, duplicates=duplicates)


async def load_presence(
    conn: asyncpg.Connection, settings: Settings, user: CurrentUser
) -> list[PresenceItem]:
    visible_ids = await visible_employee_ids(conn, user)
    rows = await conn.fetch(
        """
        SELECT d.id, d.employee_id, e.full_name,
               COALESCE(dep.name, e.department_name) AS department_name, d.hostname,
               d.is_approved, d.last_seen, d.last_activity_state
        FROM devices d
        LEFT JOIN employees e ON e.id = d.employee_id
        LEFT JOIN departments dep ON dep.id = e.department_id
        ORDER BY e.full_name NULLS LAST, d.hostname
        """
    )
    result: list[PresenceItem] = []
    for row in rows:
        if visible_ids is not None and row["employee_id"] not in visible_ids:
            continue
        snapshot = calculate_presence(
            row["last_seen"], row["last_activity_state"], ttl_seconds=settings.presence_ttl_seconds
        )
        result.append(
            PresenceItem(
                device_id=row["id"],
                employee_id=row["employee_id"],
                employee_name=row["full_name"],
                department_name=row["department_name"],
                hostname=row["hostname"],
                is_approved=row["is_approved"],
                is_online=snapshot.is_online,
                status=snapshot.status,
                last_seen=row["last_seen"],
                seconds_since_seen=snapshot.seconds_since_seen,
            )
        )
    return result


@app.get("/api/v1/presence", response_model=list[PresenceItem])
async def presence_list(
    conn: asyncpg.Connection = Depends(db),
    settings: Settings = Depends(get_settings),
    user: CurrentUser = Depends(require_permission("presence:view")),
) -> list[PresenceItem]:
    return await load_presence(conn, settings, user)


@app.get("/api/v1/timeline", response_model=TimelineResponse)
async def timeline(
    range_start: datetime = Query(alias="from"),
    range_end: datetime = Query(alias="to"),
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("timeline:view")),
) -> TimelineResponse:
    if range_start.tzinfo is None or range_end.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Timeline range must include timezone")
    if range_end <= range_start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "'to' must be after 'from'")
    if range_end - range_start > timedelta(days=31):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Timeline range is limited to 31 days")

    visible_ids = await visible_employee_ids(conn, user)
    device_query = """
        SELECT d.id, d.employee_id, d.hostname, e.full_name,
               COALESCE(dep.name, e.department_name) AS department_name
        FROM devices d
        LEFT JOIN employees e ON e.id = d.employee_id
        LEFT JOIN departments dep ON dep.id = e.department_id
    """
    if visible_ids is None:
        device_rows = await conn.fetch(device_query + " ORDER BY e.full_name NULLS LAST, d.hostname")
    elif visible_ids:
        device_rows = await conn.fetch(
            device_query + " WHERE d.employee_id = ANY($1::uuid[]) ORDER BY e.full_name NULLS LAST, d.hostname",
            list(visible_ids),
        )
    else:
        device_rows = []
    visible_device_ids = [row["id"] for row in device_rows]
    event_rows = [] if not visible_device_ids else await conn.fetch(
        """
        SELECT event_uuid, device_id, ts_start, ts_end, state,
               app_name, process_name, window_title, url_domain, url_path, category_id
        FROM activity_events
        WHERE ts_start < $2 AND ts_end > $1 AND device_id = ANY($3::uuid[])
        ORDER BY device_id, ts_start
        """,
        range_start,
        range_end,
        visible_device_ids,
    )
    events_by_device: dict[UUID, list[asyncpg.Record]] = {}
    for row in event_rows:
        events_by_device.setdefault(row["device_id"], []).append(row)

    employee_timelines: list[EmployeeTimeline] = []
    for device in device_rows:
        totals = {
            "productive": 0,
            "neutral": 0,
            "unproductive": 0,
            "idle": 0,
            "locked": 0,
            "break_time": 0,
        }
        segments: list[TimelineSegment] = []
        for event in events_by_device.get(device["id"], []):
            segment_start = max(event["ts_start"], range_start)
            segment_end = min(event["ts_end"], range_end)
            duration = clipped_duration(event["ts_start"], event["ts_end"], range_start, range_end)
            totals_key = {
                "PRODUCTIVE": "productive",
                "NEUTRAL": "neutral",
                "UNPRODUCTIVE": "unproductive",
                "IDLE": "idle",
                "LOCKED": "locked",
                "BREAK": "break_time",
            }[event["state"]]
            totals[totals_key] += duration
            segments.append(
                TimelineSegment(
                    event_uuid=event["event_uuid"],
                    ts_start=segment_start,
                    ts_end=segment_end,
                    duration_sec=duration,
                    state=event["state"],
                    app_name=event["app_name"],
                    process_name=event["process_name"],
                    window_title=event["window_title"],
                    url_domain=event["url_domain"],
                    url_path=event["url_path"],
                    category_id=event["category_id"],
                )
            )
        employee_timelines.append(
            EmployeeTimeline(
                device_id=device["id"],
                employee_id=device["employee_id"],
                employee_name=device["full_name"],
                department_name=device["department_name"],
                hostname=device["hostname"],
                segments=segments,
                totals=TimelineTotals(**totals),
            )
        )

    return TimelineResponse(
        range_start=range_start,
        range_end=range_end,
        employees=employee_timelines,
    )


@app.websocket("/api/v1/ws/presence")
async def presence_socket(websocket: WebSocket) -> None:
    token = websocket.cookies.get(ACCESS_COOKIE)
    if not token:
        await websocket.close(code=4401)
        return
    try:
        async for conn in connection():
            user = await authenticate_access_token(conn, token, get_settings())
            if "presence:view" not in user.permissions:
                await websocket.close(code=4403)
                return
    except HTTPException:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        while True:
            # A snapshot makes reconnects and missed pub/sub messages harmless.
            async for conn in connection():
                try:
                    user = await authenticate_access_token(conn, token, get_settings())
                except HTTPException:
                    await websocket.close(code=4401)
                    return
                items = await load_presence(conn, get_settings(), user)
                await websocket.send_json([item.model_dump(mode="json") for item in items])
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        return


@app.websocket("/api/v1/ws/notifications")
async def notifications_socket(websocket: WebSocket) -> None:
    token = websocket.cookies.get(ACCESS_COOKIE)
    if not token:
        await websocket.close(code=4401); return
    try:
        async for conn in connection():
            user = await authenticate_access_token(conn, token, get_settings())
            if "timeline:view" not in user.permissions:
                await websocket.close(code=4403); return
            break
    except HTTPException:
        await websocket.close(code=4401); return
    await websocket.accept()
    last_id = -1
    try:
        while True:
            async for conn in connection():
                rows = await conn.fetch(
                    """SELECT id,notification_type,payload_json AS payload,is_read,created_at
                       FROM notifications WHERE user_id=$1 ORDER BY created_at DESC LIMIT 50""", user.id,
                )
                current_id = rows[0]["id"] if rows else 0
                if current_id != last_id:
                    await websocket.send_json([{key: (value.isoformat() if isinstance(value, datetime) else value)
                                                for key, value in dict(row).items()} for row in rows])
                    last_id = current_id
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        return
