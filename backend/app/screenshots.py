import hashlib
import io
import re
import zipfile
from datetime import datetime
from pathlib import PurePosixPath
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from .auth import CurrentUser, require_permission, visible_employee_ids
from .config import Settings, get_settings
from .database import connection
from .screenshot_schemas import ScreenshotItem, ScreenshotList, ScreenshotUploadResponse
from .storage import ObjectStorage
from .upload_validation import has_valid_signature


router = APIRouter(prefix="/api/v1", tags=["screenshots"])
ALLOWED_IMAGE_TYPES = {"image/webp": ".webp", "image/jpeg": ".jpg"}
PHASH_RE = re.compile(r"^[0-9a-fA-F]{16}$")
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024
MAX_THUMB_BYTES = 1 * 1024 * 1024


async def db() -> asyncpg.Connection:
    async for conn in connection():
        yield conn


def phash_distance(left: str, right: str) -> int:
    if not PHASH_RE.fullmatch(left) or not PHASH_RE.fullmatch(right):
        raise ValueError("pHash должен быть 16-символьным hex")
    return (int(left, 16) ^ int(right, 16)).bit_count()


@router.post("/devices/{device_id}/screenshot", status_code=202)
async def request_manual_screenshot(
    device_id: UUID,
    request: Request,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("screenshot:view")),
) -> dict[str, str]:
    device = await conn.fetchrow("SELECT id,employee_id,is_approved,last_seen,last_activity_state FROM devices WHERE id=$1", device_id)
    if device is None or not device["is_approved"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Одобренное устройство не найдено")
    await ensure_employee_scope(conn, user, device["employee_id"])
    if device["last_seen"] is None or device["last_activity_state"] in {"BREAK", "LOCKED"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Снимок сейчас недоступен")
    command_id = await conn.fetchval(
        """INSERT INTO agent_commands(device_id,command,payload_json,requested_by)
           VALUES($1,'take_screenshot','{}'::jsonb,$2) RETURNING id""", device_id, user.id,
    )
    ip = request.headers.get("x-forwarded-for", "").rsplit(",", 1)[-1].strip() or (request.client.host if request.client else None)
    await conn.execute("""INSERT INTO audit_log(user_id,action,object_type,object_id,target_employee_id,ip_address,user_agent)
                          VALUES($1,'manual_screenshot_requested','device',$2,$3,$4::inet,$5)""",
                       user.id, str(device_id), device["employee_id"], ip, request.headers.get("user-agent"))
    return {"command_id": str(command_id)}


async def authenticated_screenshot_device(
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
    if not device["is_approved"] or device["employee_id"] is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Device is not approved")
    return device


def screenshot_item(row: asyncpg.Record) -> ScreenshotItem:
    return ScreenshotItem(
        **{key: row[key] for key in (
            "id", "employee_id", "employee_name", "device_id", "hostname", "taken_at",
            "monitor_index", "width", "height", "size_bytes", "is_blurred", "duplicate_of_id",
            "state", "category_id", "category_name", "app_name", "url_domain",
        )},
        thumbnail_url=f"/api/v1/screenshots/{row['id']}/thumbnail",
        image_url=f"/api/v1/screenshots/{row['id']}/image",
    )


@router.post("/agent/screenshots", response_model=ScreenshotUploadResponse, status_code=201)
async def upload_screenshot(
    image: UploadFile = File(),
    thumbnail: UploadFile | None = File(default=None),
    taken_at: datetime = Form(),
    width: int = Form(gt=0, le=20_000),
    height: int = Form(gt=0, le=20_000),
    monitor_index: int = Form(default=0, ge=0, le=32),
    phash: str | None = Form(default=None),
    is_blurred: bool = Form(default=False),
    state: str | None = Form(default=None),
    category_id: int | None = Form(default=None),
    app_name: str | None = Form(default=None),
    url_domain: str | None = Form(default=None),
    device: asyncpg.Record = Depends(authenticated_screenshot_device),
    conn: asyncpg.Connection = Depends(db),
) -> ScreenshotUploadResponse:
    if taken_at.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "taken_at must include timezone")
    if state in {"BREAK", "LOCKED", "ABSENCE"}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Screenshots are disabled for this state")
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only WebP or JPEG is allowed")
    if phash is not None and not PHASH_RE.fullmatch(phash):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid pHash")
    image_bytes = await image.read(MAX_SCREENSHOT_BYTES + 1)
    if len(image_bytes) > MAX_SCREENSHOT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Screenshot is too large")
    if not has_valid_signature(image.content_type, image_bytes):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Image signature does not match MIME type")
    thumb_bytes = None
    if thumbnail is not None:
        if thumbnail.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Invalid thumbnail type")
        thumb_bytes = await thumbnail.read(MAX_THUMB_BYTES + 1)
        if len(thumb_bytes) > MAX_THUMB_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Thumbnail is too large")
        if not has_valid_signature(thumbnail.content_type, thumb_bytes):
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Thumbnail signature does not match MIME type")

    duplicate_of_id = None
    if phash:
        previous = await conn.fetchrow(
            """
            SELECT COALESCE(duplicate_of_id, id) AS root_id, phash FROM screenshots
            WHERE device_id=$1 AND monitor_index=$2 AND phash IS NOT NULL
            ORDER BY taken_at DESC LIMIT 1
            """,
            device["id"], monitor_index,
        )
        if previous and phash_distance(phash, previous["phash"]) <= 3:
            duplicate_of_id = previous["root_id"]

    event_id = await conn.fetchval(
        """
        SELECT id FROM activity_events
        WHERE device_id=$1 AND ts_start<=$2 AND ts_end>=$2
        ORDER BY ts_start DESC LIMIT 1
        """,
        device["id"],
        taken_at,
    )
    storage_key = None
    thumb_key = None
    if duplicate_of_id is None:
        extension = ALLOWED_IMAGE_TYPES[image.content_type]
        prefix = PurePosixPath("screenshots", str(taken_at.year), f"{taken_at.month:02d}", str(device["id"]))
        object_id = uuid4().hex
        storage_key = str(prefix / f"{object_id}{extension}")
        thumb_key = str(prefix / f"{object_id}.thumb{extension}") if thumb_bytes else storage_key
        storage = ObjectStorage()
        await storage.put_bytes(storage_key, image_bytes, image.content_type)
        if thumb_bytes:
            await storage.put_bytes(thumb_key, thumb_bytes, thumbnail.content_type)
    screenshot_id = await conn.fetchval(
        """
        INSERT INTO screenshots(
            employee_id, device_id, taken_at, monitor_index, storage_key, thumb_key,
            width, height, size_bytes, phash, duplicate_of_id, is_blurred,
            activity_event_id, state, category_id, app_name, url_domain, expires_at
        ) VALUES(
            $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,
            now() + interval '30 days'
        ) RETURNING id
        """,
        device["employee_id"], device["id"], taken_at, monitor_index, storage_key, thumb_key,
        width, height, len(image_bytes), phash.lower() if phash else None, duplicate_of_id,
        is_blurred, event_id, state, category_id, app_name, url_domain,
    )
    return ScreenshotUploadResponse(
        id=screenshot_id,
        duplicate=duplicate_of_id is not None,
        duplicate_of_id=duplicate_of_id,
    )


async def ensure_employee_scope(
    conn: asyncpg.Connection, user: CurrentUser, employee_id: UUID | None
) -> set[UUID] | None:
    visible = await visible_employee_ids(conn, user)
    if employee_id is not None and visible is not None and employee_id not in visible:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    return visible


@router.get("/screenshots", response_model=ScreenshotList)
async def list_screenshots(
    employee_id: UUID | None = None,
    range_start: datetime = Query(alias="from"),
    range_end: datetime = Query(alias="to"),
    state: str | None = None,
    category_id: int | None = None,
    before: datetime | None = None,
    limit: int = Query(default=60, ge=1, le=200),
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("screenshot:view")),
) -> ScreenshotList:
    if range_start >= range_end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Параметр from должен быть раньше to")
    visible = await ensure_employee_scope(conn, user, employee_id)
    rows = await conn.fetch(
        """
        SELECT s.id, s.employee_id, e.full_name AS employee_name, s.device_id, d.hostname,
               s.taken_at, s.monitor_index, s.width, s.height, s.size_bytes, s.is_blurred,
               s.duplicate_of_id, s.state, s.category_id, c.name AS category_name,
               s.app_name, s.url_domain
        FROM screenshots s
        JOIN devices d ON d.id=s.device_id
        LEFT JOIN employees e ON e.id=s.employee_id
        LEFT JOIN categories c ON c.id=s.category_id
        WHERE s.taken_at>=$1 AND s.taken_at<$2
          AND ($3::uuid IS NULL OR s.employee_id=$3)
          AND ($4::uuid[] IS NULL OR s.employee_id=ANY($4::uuid[]))
          AND ($5::text IS NULL OR s.state=$5)
          AND ($6::bigint IS NULL OR s.category_id=$6)
          AND ($7::timestamptz IS NULL OR s.taken_at<$7)
        ORDER BY s.taken_at DESC, s.id DESC LIMIT $8
        """,
        range_start, range_end, employee_id, None if visible is None else list(visible),
        state, category_id, before, limit,
    )
    items = [screenshot_item(row) for row in rows]
    return ScreenshotList(items=items, next_before=items[-1].taken_at if len(items) == limit else None)


@router.get("/screenshots/nearest", response_model=ScreenshotItem)
async def nearest_screenshot(
    employee_id: UUID,
    at: datetime,
    max_distance_sec: int = Query(default=3600, ge=1, le=86400),
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("screenshot:view")),
) -> ScreenshotItem:
    if at.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "at должен содержать часовой пояс")
    await ensure_employee_scope(conn, user, employee_id)
    row = await conn.fetchrow(
        """
        SELECT s.id,s.employee_id,e.full_name AS employee_name,s.device_id,d.hostname,
               s.taken_at,s.monitor_index,s.width,s.height,s.size_bytes,s.is_blurred,
               s.duplicate_of_id,s.state,s.category_id,c.name AS category_name,s.app_name,s.url_domain
        FROM screenshots s JOIN devices d ON d.id=s.device_id
        LEFT JOIN employees e ON e.id=s.employee_id LEFT JOIN categories c ON c.id=s.category_id
        WHERE s.employee_id=$1 AND s.taken_at BETWEEN $2-($3::int * interval '1 second') AND $2+($3::int * interval '1 second')
        ORDER BY abs(extract(epoch FROM (s.taken_at-$2))) LIMIT 1
        """,
        employee_id, at, max_distance_sec,
    )
    if row is None: raise HTTPException(status.HTTP_404_NOT_FOUND, "Рядом с событием нет скриншота")
    return screenshot_item(row)


async def screenshot_object(
    conn: asyncpg.Connection, screenshot_id: int, user: CurrentUser, thumbnail: bool
) -> tuple[asyncpg.Record, str]:
    row = await conn.fetchrow(
        """
        SELECT s.*, COALESCE(s.storage_key, source.storage_key) AS resolved_storage_key,
               COALESCE(s.thumb_key, source.thumb_key, source.storage_key) AS resolved_thumb_key
        FROM screenshots s LEFT JOIN screenshots source ON source.id=s.duplicate_of_id
        WHERE s.id=$1
        """,
        screenshot_id,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Скриншот не найден")
    await ensure_employee_scope(conn, user, row["employee_id"])
    key = row["resolved_thumb_key"] if thumbnail else row["resolved_storage_key"]
    if not key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл скриншота не найден")
    return row, key


async def screenshot_response(
    screenshot_id: int,
    thumbnail: bool,
    conn: asyncpg.Connection,
    user: CurrentUser,
    request: Request,
    download: bool = False,
) -> StreamingResponse:
    row, key = await screenshot_object(conn, screenshot_id, user, thumbnail)
    data = await ObjectStorage().get_bytes(key)
    media_type = "image/webp" if key.endswith(".webp") else "image/jpeg"
    await conn.execute(
        """
        INSERT INTO audit_log(user_id, action, object_type, object_id, target_employee_id, ip_address, user_agent)
        VALUES($1, $2, 'screenshot', $3, $4, $5::inet, $6)
        """,
        user.id,
        "screenshot_downloaded" if download else "screenshot_viewed",
        str(screenshot_id),
        row["employee_id"],
        request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip() or (request.client.host if request.client else None),
        request.headers.get("user-agent"),
    )
    headers = {"Cache-Control": "private, max-age=300"}
    if download:
        headers["Content-Disposition"] = f'attachment; filename="screenshot-{screenshot_id}.webp"'
    return StreamingResponse(io.BytesIO(data), media_type=media_type, headers=headers)


@router.get("/screenshots/export.zip")
async def export_screenshots_zip(
    employee_id: UUID,
    request: Request,
    range_start: datetime = Query(alias="from"),
    range_end: datetime = Query(alias="to"),
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("screenshot:export")),
) -> StreamingResponse:
    if range_start >= range_end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Параметр from должен быть раньше to")
    await ensure_employee_scope(conn, user, employee_id)
    rows = await conn.fetch(
        """
        SELECT s.id, s.taken_at, COALESCE(s.storage_key, source.storage_key) AS storage_key
        FROM screenshots s LEFT JOIN screenshots source ON source.id=s.duplicate_of_id
        WHERE s.employee_id=$1 AND s.taken_at>=$2 AND s.taken_at<$3
        ORDER BY s.taken_at LIMIT 500
        """,
        employee_id, range_start, range_end,
    )
    archive = io.BytesIO()
    storage = ObjectStorage()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
        for row in rows:
            if row["storage_key"]:
                content = await storage.get_bytes(row["storage_key"])
                extension = ".webp" if row["storage_key"].endswith(".webp") else ".jpg"
                output.writestr(f"{row['taken_at'].strftime('%Y%m%d-%H%M%S')}-{row['id']}{extension}", content)
    archive.seek(0)
    await conn.execute(
        """
        INSERT INTO audit_log(user_id, action, object_type, object_id, target_employee_id, details_json, ip_address, user_agent)
        VALUES($1, 'screenshots_exported', 'employee', $2, $3, jsonb_build_object('count', $4), $5::inet, $6)
        """,
        user.id, str(employee_id), employee_id, len(rows),
        request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip() or (request.client.host if request.client else None),
        request.headers.get("user-agent"),
    )
    return StreamingResponse(
        archive,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="screenshots.zip"'},
    )


@router.get("/screenshots/{screenshot_id}/thumbnail")
async def get_screenshot_thumbnail(
    screenshot_id: int,
    request: Request,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("screenshot:view")),
) -> StreamingResponse:
    return await screenshot_response(screenshot_id, True, conn, user, request)


@router.get("/screenshots/{screenshot_id}/image")
async def get_screenshot_image(
    screenshot_id: int,
    request: Request,
    download: bool = False,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("screenshot:view")),
) -> StreamingResponse:
    if download and "screenshot:export" not in user.permissions:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав для скачивания")
    return await screenshot_response(screenshot_id, False, conn, user, request, download)
