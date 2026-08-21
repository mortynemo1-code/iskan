import json
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status

from .auth import CurrentUser, require_permission
from .database import connection
from .settings_schemas import (
    AppearanceSettings,
    AuditItem,
    AuditPage,
    ColorSchemeCreate,
    ColorSchemeItem,
    NotificationItem,
    RetentionPolicy,
    ScopedSettingsItem,
    ScopedSettingsUpdate,
    ThresholdSchemeCreate,
    ThresholdSchemeItem,
)


router = APIRouter(prefix="/api/v1", tags=["settings"])


async def db() -> asyncpg.Connection:
    async for conn in connection(): yield conn


async def setting_audit(conn: asyncpg.Connection, user: CurrentUser, action: str, object_type: str, object_id: str, details: dict | None = None) -> None:
    await conn.execute("""INSERT INTO audit_log(user_id,action,object_type,object_id,details_json)
                          VALUES($1,$2,$3,$4,$5::jsonb)""", user.id, action, object_type, object_id,
                       json.dumps(details or {}, default=str))


def color_item(row: asyncpg.Record) -> ColorSchemeItem:
    return ColorSchemeItem(id=row["id"], name=row["name"], colors=row["colors_json"], patterns_enabled=row["patterns_enabled"], is_default=row["is_default"], created_at=row["created_at"])


def threshold_item(row: asyncpg.Record) -> ThresholdSchemeItem:
    return ThresholdSchemeItem(id=row["id"], name=row["name"], rules=row["rules_json"], scope_type=row["scope_type"], scope_id=row["scope_id"], is_default=row["is_default"], created_at=row["created_at"])


@router.get("/color-schemes", response_model=list[ColorSchemeItem])
async def list_color_schemes(conn: asyncpg.Connection = Depends(db), _: CurrentUser = Depends(require_permission("timeline:view"))) -> list[ColorSchemeItem]:
    return [color_item(row) for row in await conn.fetch("SELECT * FROM color_schemes ORDER BY is_default DESC,name")]


@router.post("/color-schemes", response_model=ColorSchemeItem, status_code=201)
async def create_color_scheme(payload: ColorSchemeCreate, conn: asyncpg.Connection = Depends(db), user: CurrentUser = Depends(require_permission("settings:manage"))) -> ColorSchemeItem:
    try:
        row = await conn.fetchrow("""INSERT INTO color_schemes(name,colors_json,patterns_enabled) VALUES($1,$2::jsonb,$3) RETURNING *""",
                                  payload.name, json.dumps(payload.colors), payload.patterns_enabled)
    except asyncpg.UniqueViolationError as error: raise HTTPException(status.HTTP_409_CONFLICT, "Схема с таким названием существует") from error
    await setting_audit(conn, user, "color_scheme_created", "color_scheme", str(row["id"]))
    return color_item(row)


@router.patch("/color-schemes/{scheme_id}", response_model=ColorSchemeItem)
async def update_color_scheme(scheme_id: UUID, payload: ColorSchemeCreate, conn: asyncpg.Connection = Depends(db), user: CurrentUser = Depends(require_permission("settings:manage"))) -> ColorSchemeItem:
    row = await conn.fetchrow("""UPDATE color_schemes SET name=$2,colors_json=$3::jsonb,patterns_enabled=$4,updated_at=now()
                               WHERE id=$1 RETURNING *""", scheme_id, payload.name, json.dumps(payload.colors), payload.patterns_enabled)
    if row is None: raise HTTPException(status.HTTP_404_NOT_FOUND, "Схема не найдена")
    await setting_audit(conn, user, "color_scheme_updated", "color_scheme", str(scheme_id))
    return color_item(row)


@router.delete("/color-schemes/{scheme_id}", status_code=204)
async def delete_color_scheme(scheme_id: UUID, conn: asyncpg.Connection = Depends(db), user: CurrentUser = Depends(require_permission("settings:manage"))) -> None:
    row = await conn.fetchrow("DELETE FROM color_schemes WHERE id=$1 AND is_default=false RETURNING id", scheme_id)
    if row is None: raise HTTPException(status.HTTP_409_CONFLICT, "Системную или отсутствующую схему удалить нельзя")
    await setting_audit(conn, user, "color_scheme_deleted", "color_scheme", str(scheme_id))


@router.get("/threshold-schemes", response_model=list[ThresholdSchemeItem])
async def list_threshold_schemes(conn: asyncpg.Connection = Depends(db), _: CurrentUser = Depends(require_permission("timeline:view"))) -> list[ThresholdSchemeItem]:
    return [threshold_item(row) for row in await conn.fetch("SELECT * FROM threshold_schemes ORDER BY is_default DESC,name")]


@router.post("/threshold-schemes", response_model=ThresholdSchemeItem, status_code=201)
async def create_threshold_scheme(payload: ThresholdSchemeCreate, conn: asyncpg.Connection = Depends(db), user: CurrentUser = Depends(require_permission("settings:manage"))) -> ThresholdSchemeItem:
    try:
        row = await conn.fetchrow("""INSERT INTO threshold_schemes(name,rules_json,scope_type,scope_id)
                                     VALUES($1,$2::jsonb,$3,$4) RETURNING *""", payload.name, json.dumps(payload.rules), payload.scope_type, payload.scope_id)
    except asyncpg.UniqueViolationError as error: raise HTTPException(status.HTTP_409_CONFLICT, "Пороговая схема с таким названием существует") from error
    await setting_audit(conn, user, "threshold_scheme_created", "threshold_scheme", str(row["id"]))
    return threshold_item(row)


@router.patch("/threshold-schemes/{scheme_id}", response_model=ThresholdSchemeItem)
async def update_threshold_scheme(scheme_id: UUID, payload: ThresholdSchemeCreate, conn: asyncpg.Connection = Depends(db), user: CurrentUser = Depends(require_permission("settings:manage"))) -> ThresholdSchemeItem:
    row = await conn.fetchrow("""UPDATE threshold_schemes SET name=$2,rules_json=$3::jsonb,scope_type=$4,scope_id=$5,updated_at=now()
                               WHERE id=$1 RETURNING *""", scheme_id, payload.name, json.dumps(payload.rules), payload.scope_type, payload.scope_id)
    if row is None: raise HTTPException(status.HTTP_404_NOT_FOUND, "Схема не найдена")
    await setting_audit(conn, user, "threshold_scheme_updated", "threshold_scheme", str(scheme_id))
    return threshold_item(row)


@router.delete("/threshold-schemes/{scheme_id}", status_code=204)
async def delete_threshold_scheme(scheme_id: UUID, conn: asyncpg.Connection = Depends(db), user: CurrentUser = Depends(require_permission("settings:manage"))) -> None:
    row = await conn.fetchrow("DELETE FROM threshold_schemes WHERE id=$1 AND is_default=false RETURNING id", scheme_id)
    if row is None: raise HTTPException(status.HTTP_409_CONFLICT, "Системную или отсутствующую схему удалить нельзя")
    await setting_audit(conn, user, "threshold_scheme_deleted", "threshold_scheme", str(scheme_id))


@router.get("/settings/appearance", response_model=AppearanceSettings)
async def get_appearance(conn: asyncpg.Connection = Depends(db), _: CurrentUser = Depends(require_permission("timeline:view"))) -> AppearanceSettings:
    value = await conn.fetchval("SELECT value_json FROM settings WHERE key='appearance.default'") or {}
    color = await conn.fetchrow("SELECT * FROM color_schemes WHERE id=$1", value.get("color_scheme_id"))
    threshold = await conn.fetchrow("SELECT * FROM threshold_schemes WHERE id=$1", value.get("threshold_scheme_id"))
    if color is None: color = await conn.fetchrow("SELECT * FROM color_schemes ORDER BY is_default DESC LIMIT 1")
    if threshold is None: threshold = await conn.fetchrow("SELECT * FROM threshold_schemes ORDER BY is_default DESC LIMIT 1")
    return AppearanceSettings(color_scheme_id=color["id"], threshold_scheme_id=threshold["id"], color_scheme=color_item(color), threshold_scheme=threshold_item(threshold))


@router.put("/settings/appearance", response_model=AppearanceSettings)
async def set_appearance(payload: AppearanceSettings, conn: asyncpg.Connection = Depends(db), user: CurrentUser = Depends(require_permission("settings:manage"))) -> AppearanceSettings:
    if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM color_schemes WHERE id=$1)", payload.color_scheme_id): raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Цветовая схема не найдена")
    if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM threshold_schemes WHERE id=$1)", payload.threshold_scheme_id): raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Пороговая схема не найдена")
    await conn.execute("""INSERT INTO settings(key,value_json) VALUES('appearance.default',$1::jsonb)
                          ON CONFLICT(key) DO UPDATE SET value_json=EXCLUDED.value_json,updated_at=now()""",
                       json.dumps({"color_scheme_id": str(payload.color_scheme_id), "threshold_scheme_id": str(payload.threshold_scheme_id)}))
    await setting_audit(conn, user, "appearance_updated", "settings", "appearance.default")
    return await get_appearance(conn, user)


@router.get("/settings/agent", response_model=list[ScopedSettingsItem])
async def get_agent_settings(conn: asyncpg.Connection = Depends(db), _: CurrentUser = Depends(require_permission("settings:manage"))) -> list[ScopedSettingsItem]:
    rows = await conn.fetch("SELECT key,scope_type,scope_id,value_json AS value,updated_at FROM scoped_settings WHERE key='agent' ORDER BY scope_type,updated_at DESC")
    base = await conn.fetchrow("SELECT value_json AS value,updated_at FROM settings WHERE key='agent.default'")
    result = [ScopedSettingsItem(key="agent", scope_type="global", scope_id=None, value=base["value"], updated_at=base["updated_at"])] if base else []
    result.extend(ScopedSettingsItem(**dict(row)) for row in rows)
    return result


@router.put("/settings/agent", response_model=ScopedSettingsItem)
async def set_agent_settings(payload: ScopedSettingsUpdate, conn: asyncpg.Connection = Depends(db), user: CurrentUser = Depends(require_permission("settings:manage"))) -> ScopedSettingsItem:
    if payload.scope_type != "global" and payload.scope_id is None: raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Для скоупа нужен scope_id")
    if payload.scope_type == "global" and payload.scope_id is None:
        row = await conn.fetchrow("""INSERT INTO settings(key,value_json) VALUES('agent.default',$1::jsonb)
                                     ON CONFLICT(key) DO UPDATE SET value_json=settings.value_json || EXCLUDED.value_json,updated_at=now()
                                     RETURNING value_json AS value,updated_at""", json.dumps(payload.value))
    else:
        row = await conn.fetchrow("""INSERT INTO scoped_settings(key,scope_type,scope_id,value_json,updated_by)
                                     VALUES('agent',$1,$2,$3::jsonb,$4)
                                     ON CONFLICT(key,scope_type,scope_id) DO UPDATE SET value_json=EXCLUDED.value_json,updated_by=EXCLUDED.updated_by,updated_at=now()
                                     RETURNING value_json AS value,updated_at""", payload.scope_type, payload.scope_id, json.dumps(payload.value), user.id)
    await setting_audit(conn, user, "agent_settings_updated", "settings", f"{payload.scope_type}:{payload.scope_id}", payload.value)
    return ScopedSettingsItem(key="agent", scope_type=payload.scope_type, scope_id=payload.scope_id, value=row["value"], updated_at=row["updated_at"])


@router.get("/settings/retention", response_model=list[RetentionPolicy])
async def get_retention(conn: asyncpg.Connection = Depends(db), _: CurrentUser = Depends(require_permission("settings:manage"))) -> list[RetentionPolicy]:
    return [RetentionPolicy(**dict(row)) for row in await conn.fetch("SELECT id,data_type,scope_type,scope_id,days FROM retention_policies ORDER BY data_type,scope_type")]


@router.put("/settings/retention", response_model=RetentionPolicy)
async def set_retention(payload: RetentionPolicy, conn: asyncpg.Connection = Depends(db), user: CurrentUser = Depends(require_permission("settings:manage"))) -> RetentionPolicy:
    if payload.scope_type != "global" and payload.scope_id is None: raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Для скоупа нужен scope_id")
    row = await conn.fetchrow("""INSERT INTO retention_policies(data_type,scope_type,scope_id,days) VALUES($1,$2,$3,$4)
                               ON CONFLICT(data_type,scope_type,scope_id) DO UPDATE SET days=EXCLUDED.days,updated_at=now()
                               RETURNING id,data_type,scope_type,scope_id,days""", payload.data_type, payload.scope_type, payload.scope_id, payload.days)
    await setting_audit(conn, user, "retention_updated", "retention", f"{payload.data_type}:{payload.scope_type}:{payload.scope_id}", {"days": payload.days})
    return RetentionPolicy(**dict(row))


@router.get("/audit-log", response_model=AuditPage)
async def audit_log(page: int = Query(default=1, ge=1), per_page: int = Query(default=100, ge=1, le=500), action: str | None = None,
                    user_id: UUID | None = None, range_start: str | None = Query(default=None, alias="from"), range_end: str | None = Query(default=None, alias="to"),
                    conn: asyncpg.Connection = Depends(db), _: CurrentUser = Depends(require_permission("audit:view"))) -> AuditPage:
    rows = await conn.fetch("""SELECT a.id,a.user_id,u.display_name AS user_name,a.action,a.object_type,a.object_id,a.target_employee_id,
                              e.full_name AS target_employee_name,a.ip_address::text,a.user_agent,a.details_json AS details,a.created_at,
                              count(*) OVER()::int AS total FROM audit_log a LEFT JOIN users u ON u.id=a.user_id LEFT JOIN employees e ON e.id=a.target_employee_id
                              WHERE ($1::text IS NULL OR a.action=$1) AND ($2::uuid IS NULL OR a.user_id=$2)
                                AND ($3::timestamptz IS NULL OR a.created_at>=$3::timestamptz) AND ($4::timestamptz IS NULL OR a.created_at<$4::timestamptz)
                              ORDER BY a.created_at DESC LIMIT $5 OFFSET $6""", action, user_id, range_start, range_end, per_page, (page - 1) * per_page)
    return AuditPage(items=[AuditItem(**{key: row[key] for key in AuditItem.model_fields}) for row in rows], total=rows[0]["total"] if rows else 0, page=page, per_page=per_page)


@router.get("/notifications", response_model=list[NotificationItem])
async def notifications(unread_only: bool = False, conn: asyncpg.Connection = Depends(db), user: CurrentUser = Depends(require_permission("timeline:view"))) -> list[NotificationItem]:
    rows = await conn.fetch("""SELECT id,notification_type,payload_json AS payload,is_read,created_at FROM notifications
                              WHERE user_id=$1 AND ($2::boolean=false OR is_read=false) ORDER BY created_at DESC LIMIT 200""", user.id, unread_only)
    return [NotificationItem(**dict(row)) for row in rows]


@router.post("/notifications/{notification_id}/read", status_code=204)
async def read_notification(notification_id: int, conn: asyncpg.Connection = Depends(db), user: CurrentUser = Depends(require_permission("timeline:view"))) -> None:
    result = await conn.execute("UPDATE notifications SET is_read=true WHERE id=$1 AND user_id=$2", notification_id, user.id)
    if result.endswith(" 0"): raise HTTPException(status.HTTP_404_NOT_FOUND, "Уведомление не найдено")
