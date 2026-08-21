import hashlib
import json
import secrets
from datetime import UTC, datetime
from urllib.parse import quote, urlencode
from uuid import UUID

import asyncpg
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from .auth import CurrentUser, require_permission, visible_employee_ids
from .config import Settings, get_settings
from .database import connection
from .stream_schemas import (
    AgentCommand,
    ArchiveClipRequest,
    ArchiveClipResponse,
    ArchiveSpan,
    CommandAck,
    PinRequest,
    StreamSessionItem,
    StreamStartRequest,
)
from .stream_policy_jobs import _resolved_config, within_work_schedule


router = APIRouter(prefix="/api/v1", tags=["streams"])


async def db() -> asyncpg.Connection:
    async with connection() as conn:
        yield conn


async def authenticated_stream_device(
    authorization: str | None = Header(default=None),
    conn: asyncpg.Connection = Depends(db),
    settings: Settings = Depends(get_settings),
) -> asyncpg.Record:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Device token is required")
    token_hash = hashlib.sha256(f"{settings.device_token_pepper}:{authorization[7:]}".encode()).hexdigest()
    device = await conn.fetchrow("SELECT * FROM devices WHERE token_hash=$1", token_hash)
    if device is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid device token")
    return device


async def ensure_scope(conn: asyncpg.Connection, user: CurrentUser, employee_id: UUID) -> None:
    visible = await visible_employee_ids(conn, user)
    if visible is not None and employee_id not in visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")


def stream_urls(stream_key: str) -> tuple[str, str, str]:
    path = quote(stream_key, safe="")
    return f"/webrtc/{path}", f"/webrtc/{path}/whep", f"/hls/{path}/index.m3u8"


def stream_item(row: asyncpg.Record) -> StreamSessionItem:
    viewer, whep, hls = stream_urls(row["stream_key"])
    return StreamSessionItem(
        **{key: row[key] for key in (
            "id", "employee_id", "employee_name", "department_name", "device_id", "hostname",
            "started_at", "ended_at", "profile", "status", "mode",
        )},
        viewer_url=viewer,
        whep_url=whep,
        hls_url=hls,
    )


async def audit_access(
    conn: asyncpg.Connection,
    user: CurrentUser,
    request: Request,
    action: str,
    employee_id: UUID,
    object_id: str,
    details: dict | None = None,
) -> None:
    forwarded = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    ip = forwarded or (request.client.host if request.client else None)
    deduplicate = action in {"stream_viewed", "stream_archive_played"}
    await conn.execute(
        """
        INSERT INTO audit_log(user_id, action, object_type, object_id, target_employee_id, details_json, ip_address, user_agent)
        SELECT $1,$2,'stream',$3,$4,$5::jsonb,$6::inet,$7
        WHERE NOT $8::boolean OR NOT EXISTS(
          SELECT 1 FROM audit_log WHERE user_id=$1 AND action=$2 AND object_id=$3 AND created_at>now()-interval '5 minutes'
        )
        """,
        user.id, action, object_id, employee_id, json.dumps({"ip": ip, **(details or {})}, default=str), ip,
        request.headers.get("user-agent"), deduplicate,
    )


@router.post("/stream/request/{employee_id}", response_model=StreamSessionItem, status_code=202)
async def request_stream(
    employee_id: UUID,
    payload: StreamStartRequest,
    request: Request,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("stream:live")),
    settings: Settings = Depends(get_settings),
) -> StreamSessionItem:
    await ensure_scope(conn, user, employee_id)
    device = await conn.fetchrow(
        """
        SELECT d.*, e.full_name AS employee_name, COALESCE(dep.name,e.department_name) AS department_name,
               e.department_id,e.timezone,
               (SELECT s.rules_json FROM schedule_assignments sa JOIN schedules s ON s.id=sa.schedule_id
                WHERE sa.employee_id=e.id AND sa.valid_from<=current_date AND (sa.valid_to IS NULL OR sa.valid_to>=current_date)
                ORDER BY sa.valid_from DESC LIMIT 1) AS work_schedule,
               EXISTS(SELECT 1 FROM holidays h WHERE h.holiday_date=current_date AND h.kind='holiday') AS is_holiday
        FROM devices d JOIN employees e ON e.id=d.employee_id
        LEFT JOIN departments dep ON dep.id=e.department_id
        WHERE d.employee_id=$1 AND d.is_approved=true
        ORDER BY d.last_seen DESC NULLS LAST LIMIT 1
        """, employee_id,
    )
    if device is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "У сотрудника нет одобренного устройства")
    if device["last_seen"] is None or (datetime.now(UTC) - device["last_seen"]).total_seconds() > 90:
        raise HTTPException(status.HTTP_409_CONFLICT, "Устройство сотрудника не в сети")
    if device["last_activity_state"] in {"BREAK", "LOCKED"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Трансляция запрещена во время перерыва или блокировки")
    agent_config = await _resolved_config(conn, employee_id, device["department_id"])
    if not within_work_schedule(device["work_schedule"], datetime.now(UTC), device["timezone"], int(agent_config.get("schedule_grace_minutes", 60)), device["is_holiday"]):
        raise HTTPException(status.HTTP_409_CONFLICT, "Трансляция запрещена вне рабочего графика")

    await conn.execute(
        """UPDATE stream_sessions SET status='ended', ended_at=now()
           WHERE employee_id=$1 AND status IN ('requested','starting','live')""", employee_id,
    )
    stream_key = f"wm-{secrets.token_urlsafe(24)}"
    row = await conn.fetchrow(
        """
        INSERT INTO stream_sessions(device_id, employee_id, profile, status, initiated_by, mode, stream_key, storage_prefix)
        VALUES($1,$2,$3,'requested',$4,$5,$6,$6)
        RETURNING id, device_id, employee_id, started_at, ended_at, profile, status, mode, stream_key
        """, device["id"], employee_id, payload.profile, user.id, payload.mode, stream_key,
    )
    publish_url = f"{settings.mediamtx_publish_url.rstrip('/')}/{stream_key}/whip"
    command_payload = {
        "session_id": str(row["id"]), "publish_url": publish_url, "profile": payload.profile,
        "rtsp_url": f"{settings.mediamtx_rtsp_publish_url.rstrip('/')}/{stream_key}", "stream_key": stream_key,
    }
    await conn.execute(
        """INSERT INTO agent_commands(device_id, command, payload_json, requested_by)
           VALUES($1,'start_stream',$2::jsonb,$3)""",
        device["id"], json.dumps(command_payload), user.id,
    )
    combined = dict(row) | {
        "employee_name": device["employee_name"], "department_name": device["department_name"],
        "hostname": device["hostname"],
    }
    await audit_access(conn, user, request, "stream_requested", employee_id, str(row["id"]), {"profile": payload.profile})
    return stream_item(combined)


@router.post("/stream/stop/{employee_id}", status_code=202)
async def stop_stream(
    employee_id: UUID,
    request: Request,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("stream:live")),
) -> dict[str, bool]:
    await ensure_scope(conn, user, employee_id)
    session = await conn.fetchrow(
        """SELECT * FROM stream_sessions WHERE employee_id=$1 AND status IN ('requested','starting','live')
           ORDER BY started_at DESC LIMIT 1""", employee_id,
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Активная трансляция не найдена")
    await conn.execute(
        """INSERT INTO agent_commands(device_id,command,payload_json,requested_by)
           VALUES($1,'stop_stream',$2::jsonb,$3)""",
        session["device_id"], json.dumps({"session_id": str(session["id"])}), user.id,
    )
    await conn.execute("UPDATE stream_sessions SET status='ended',ended_at=now() WHERE id=$1", session["id"])
    await audit_access(conn, user, request, "stream_stopped", employee_id, str(session["id"]))
    return {"accepted": True}


@router.get("/stream/wall", response_model=list[StreamSessionItem])
async def stream_wall(
    request: Request,
    department_id: UUID | None = None,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("stream:live")),
) -> list[StreamSessionItem]:
    visible = await visible_employee_ids(conn, user)
    rows = await conn.fetch(
        """
        SELECT DISTINCT ON (s.employee_id) s.id,s.employee_id,s.device_id,s.started_at,s.ended_at,
               s.profile,s.status,s.mode,s.stream_key,d.hostname,e.full_name AS employee_name,
               COALESCE(dep.name,e.department_name) AS department_name
        FROM stream_sessions s JOIN devices d ON d.id=s.device_id JOIN employees e ON e.id=s.employee_id
        LEFT JOIN departments dep ON dep.id=e.department_id
        WHERE s.status IN ('requested','starting','live')
          AND ($1::uuid IS NULL OR e.department_id=$1)
          AND ($2::uuid[] IS NULL OR s.employee_id=ANY($2::uuid[]))
        ORDER BY s.employee_id,s.started_at DESC LIMIT 16
        """, department_id, None if visible is None else list(visible),
    )
    for row in rows:
        await audit_access(conn, user, request, "stream_viewed", row["employee_id"], str(row["id"]), {"wall": True})
    return [stream_item(row) for row in rows]


@router.get("/stream/archive/{employee_id}/index", response_model=list[ArchiveSpan])
async def archive_index(
    employee_id: UUID,
    request: Request,
    range_start: datetime = Query(alias="from"),
    range_end: datetime = Query(alias="to"),
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("stream:archive")),
    settings: Settings = Depends(get_settings),
) -> list[ArchiveSpan]:
    if range_start >= range_end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Параметр from должен быть раньше to")
    await ensure_scope(conn, user, employee_id)
    sessions = await conn.fetch(
        """SELECT id,stream_key FROM stream_sessions WHERE employee_id=$1 AND started_at<$3
           AND COALESCE(ended_at,now())>$2 ORDER BY started_at""", employee_id, range_start, range_end,
    )
    result: list[ArchiveSpan] = []
    async with httpx.AsyncClient(timeout=10) as client:
        for session in sessions:
            try:
                response = await client.get(
                    f"{settings.mediamtx_playback_url.rstrip('/')}/list",
                    params={"path": session["stream_key"], "start": range_start.isoformat(), "end": range_end.isoformat()},
                )
                response.raise_for_status()
                for span in response.json():
                    params = urlencode({
                        "path": session["stream_key"], "start": span["start"],
                        "duration": span["duration"], "format": "mp4",
                    })
                    result.append(ArchiveSpan(start=span["start"], duration=span["duration"], url=f"/api/v1/stream/archive/{employee_id}/playback?{params}"))
            except (httpx.HTTPError, ValueError, KeyError):
                continue
    await audit_access(conn, user, request, "stream_archive_index_viewed", employee_id, str(employee_id), {"count": len(result)})
    return result


@router.get("/stream/archive/{employee_id}/playback")
async def archive_playback(
    employee_id: UUID,
    request: Request,
    path: str = Query(min_length=10, max_length=200),
    start: str = Query(min_length=10, max_length=80),
    duration: float = Query(gt=0, le=7200),
    download: bool = False,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("stream:archive")),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    await ensure_scope(conn, user, employee_id)
    session = await conn.fetchrow("SELECT id FROM stream_sessions WHERE employee_id=$1 AND stream_key=$2", employee_id, path)
    if session is None: raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись не найдена")
    client = httpx.AsyncClient(timeout=httpx.Timeout(30, read=None))
    upstream_request = client.build_request(
        "GET", f"{settings.mediamtx_playback_url.rstrip('/')}/get",
        params={"path": path, "start": start, "duration": duration, "format": "mp4"},
        headers={"Range": request.headers["range"]} if request.headers.get("range") else None,
    )
    response = await client.send(upstream_request, stream=True)
    if response.status_code >= 400:
        await response.aclose(); await client.aclose()
        raise HTTPException(response.status_code, "Медиасервер не отдал запись")
    await audit_access(conn, user, request, "stream_archive_played", employee_id, str(session["id"]), {"start": start, "duration": duration, "download": download})
    async def content():
        try:
            async for chunk in response.aiter_bytes(): yield chunk
        finally:
            await response.aclose(); await client.aclose()
    headers = {key: value for key, value in response.headers.items() if key.lower() in {"content-length", "content-range", "accept-ranges", "etag", "last-modified"}}
    if download: headers["Content-Disposition"] = 'attachment; filename="workforce-clip.mp4"'
    return StreamingResponse(content(), status_code=response.status_code, media_type="video/mp4", headers=headers)


@router.post("/stream/clip", response_model=ArchiveClipResponse)
async def archive_clip(
    payload: ArchiveClipRequest,
    request: Request,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("stream:download")),
) -> ArchiveClipResponse:
    if payload.start >= payload.end or (payload.end - payload.start).total_seconds() > 7200:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Фрагмент должен быть от 1 секунды до 2 часов")
    await ensure_scope(conn, user, payload.employee_id)
    session = await conn.fetchrow(
        """SELECT id,stream_key FROM stream_sessions WHERE employee_id=$1 AND started_at<=$2
           AND COALESCE(ended_at,now())>$2 ORDER BY started_at DESC LIMIT 1""", payload.employee_id, payload.start,
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Запись на выбранный момент не найдена")
    params = urlencode({"path": session["stream_key"], "start": payload.start.isoformat(),
                        "duration": (payload.end - payload.start).total_seconds(), "format": "mp4"})
    await audit_access(conn, user, request, "stream_clip_downloaded", payload.employee_id, str(session["id"]),
                       {"from": payload.start, "to": payload.end})
    return ArchiveClipResponse(url=f"/api/v1/stream/archive/{payload.employee_id}/playback?{params}&download=true")


@router.post("/stream/segments/pin", status_code=202)
async def pin_segments(
    payload: PinRequest,
    request: Request,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("stream:archive")),
) -> dict[str, int]:
    if payload.start >= payload.end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Некорректный интервал")
    await ensure_scope(conn, user, payload.employee_id)
    result = await conn.execute(
        """UPDATE stream_segments ss SET is_pinned=true,pin_reason=$4
           FROM stream_sessions s WHERE ss.session_id=s.id AND s.employee_id=$1
           AND ss.ts_start<$3 AND ss.ts_start + (ss.duration_ms * interval '1 millisecond')>$2""",
        payload.employee_id, payload.start, payload.end, payload.reason,
    )
    count = int(result.rsplit(" ", 1)[-1])
    await conn.execute(
        """INSERT INTO pinned_video_ranges(employee_id,range_start,range_end,reason,pinned_by)
           VALUES($1,$2,$3,$4,$5)""",
        payload.employee_id, payload.start, payload.end, payload.reason, user.id,
    )
    await audit_access(conn, user, request, "stream_segments_pinned", payload.employee_id, str(payload.employee_id), {"count": count})
    return {"pinned": max(1, count)}


@router.get("/agent/commands", response_model=list[AgentCommand])
async def agent_commands(
    device: asyncpg.Record = Depends(authenticated_stream_device),
    conn: asyncpg.Connection = Depends(db),
) -> list[AgentCommand]:
    rows = await conn.fetch(
        """UPDATE agent_commands SET status='delivered',delivered_at=now()
           WHERE id IN (SELECT id FROM agent_commands WHERE device_id=$1 AND status='pending'
                        AND expires_at>now() ORDER BY requested_at LIMIT 20 FOR UPDATE SKIP LOCKED)
           RETURNING id,command,payload_json""", device["id"],
    )
    if rows:
        stream_ids = [UUID(str(row["payload_json"].get("session_id"))) for row in rows
                      if row["command"] == "start_stream" and row["payload_json"].get("session_id")]
        if stream_ids:
            await conn.execute("UPDATE stream_sessions SET status='starting' WHERE id=ANY($1::uuid[])", stream_ids)
    return [AgentCommand(id=row["id"], command=row["command"], payload=row["payload_json"]) for row in rows]


@router.post("/agent/commands/{command_id}/ack", status_code=202)
async def acknowledge_command(
    command_id: UUID,
    payload: CommandAck,
    device: asyncpg.Record = Depends(authenticated_stream_device),
    conn: asyncpg.Connection = Depends(db),
) -> dict[str, bool]:
    row = await conn.fetchrow(
        """UPDATE agent_commands SET status=$3,acknowledged_at=now(),
                  payload_json=payload_json || jsonb_build_object('ack_message',$4::text)
           WHERE id=$1 AND device_id=$2 AND status='delivered' RETURNING command,payload_json""",
        command_id, device["id"], "acknowledged" if payload.success else "failed", payload.message,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Команда не найдена")
    session_id = row["payload_json"].get("session_id")
    if session_id and row["command"] == "start_stream":
        await conn.execute(
            "UPDATE stream_sessions SET status=$2,failure_reason=$3 WHERE id=$1",
            UUID(str(session_id)), "live" if payload.success else "failed", payload.message,
        )
    return {"accepted": True}
