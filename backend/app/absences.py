import json
from calendar import monthrange
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from .absence_schemas import (
    AbsenceCalendar,
    AbsenceCreate,
    AbsenceDecision,
    AbsenceItem,
    AbsencePatch,
    AbsenceTypeCreate,
    AbsenceTypeItem,
    AbsenceTypePatch,
    CalendarEmployee,
    HolidayItem,
    ScheduleAssignmentCreate,
    ScheduleAssignmentItem,
    ScheduleCreate,
    ScheduleItem,
)
from .auth import CurrentUser, require_permission, visible_employee_ids
from .database import connection
from .storage import ObjectStorage
from .upload_validation import has_valid_signature


router = APIRouter(prefix="/api/v1", tags=["absences"])
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
ALLOWED_ATTACHMENTS = {
    "application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
}


async def db() -> asyncpg.Connection:
    async for conn in connection():
        yield conn


ABSENCE_SELECT = """
SELECT a.id,a.employee_id,e.full_name AS employee_name,COALESCE(d.name,e.department_name) AS department_name,
       a.type_id,t.code AS type_code,t.name AS type_name,t.color,t.effect,t.requires_document,
       a.date_from,a.date_to,a.minutes,a.reason,a.comment,a.attachment_key,a.severity,a.status,a.is_auto,
       a.created_by,a.approved_by,a.approved_at,a.created_at
FROM absences a JOIN employees e ON e.id=a.employee_id
JOIN absence_types t ON t.id=a.type_id LEFT JOIN departments d ON d.id=e.department_id
"""


async def audit(conn: asyncpg.Connection, user: CurrentUser, action: str, object_id: str, details: dict | None = None) -> None:
    await conn.execute(
        """INSERT INTO audit_log(user_id,action,object_type,object_id,details_json)
           VALUES($1,$2,'absence',$3,$4::jsonb)""",
        user.id, action, object_id, json.dumps(details or {}, default=str),
    )


async def ensure_employee_scope(conn: asyncpg.Connection, user: CurrentUser, employee_ids: set[UUID]) -> None:
    visible = await visible_employee_ids(conn, user)
    if visible is not None and not employee_ids.issubset(visible):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")


async def get_absence(conn: asyncpg.Connection, absence_id: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(ABSENCE_SELECT + " WHERE a.id=$1", absence_id)


@router.get("/absence-types", response_model=list[AbsenceTypeItem])
async def list_absence_types(
    conn: asyncpg.Connection = Depends(db),
    _: CurrentUser = Depends(require_permission("timeline:view")),
) -> list[AbsenceTypeItem]:
    rows = await conn.fetch(
        "SELECT id,code,name,color,effect,requires_document,is_system FROM absence_types ORDER BY is_system DESC,name"
    )
    return [AbsenceTypeItem(**dict(row)) for row in rows]


@router.post("/absence-types", response_model=AbsenceTypeItem, status_code=201)
async def create_absence_type(
    payload: AbsenceTypeCreate,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("settings:manage")),
) -> AbsenceTypeItem:
    try:
        row = await conn.fetchrow(
            """INSERT INTO absence_types(code,name,color,effect,requires_document)
               VALUES($1,$2,$3,$4,$5)
               RETURNING id,code,name,color,effect,requires_document,is_system""",
            payload.code, payload.name.strip(), payload.color.upper(), payload.effect, payload.requires_document,
        )
    except asyncpg.UniqueViolationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "Тип с таким кодом уже существует") from error
    await audit(conn, user, "absence_type_created", str(row["id"]))
    return AbsenceTypeItem(**dict(row))


@router.patch("/absence-types/{type_id}", response_model=AbsenceTypeItem)
async def update_absence_type(
    type_id: int,
    payload: AbsenceTypePatch,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("settings:manage")),
) -> AbsenceTypeItem:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Нет изменений")
    values: list[Any] = []
    assignments: list[str] = []
    for key, value in changes.items():
        values.append(value.upper() if key == "color" and value else value)
        assignments.append(f"{key}=${len(values)}")
    values.append(type_id)
    row = await conn.fetchrow(
        f"""UPDATE absence_types SET {','.join(assignments)},updated_at=now() WHERE id=${len(values)}
            RETURNING id,code,name,color,effect,requires_document,is_system""", *values,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тип не найден")
    await audit(conn, user, "absence_type_updated", str(type_id), changes)
    return AbsenceTypeItem(**dict(row))


@router.get("/absences", response_model=list[AbsenceItem])
async def list_absences(
    employee_id: UUID | None = None,
    range_start: date = Query(alias="from"),
    range_end: date = Query(alias="to"),
    type_id: int | None = None,
    absence_status: str | None = Query(default=None, alias="status"),
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("timeline:view")),
) -> list[AbsenceItem]:
    if range_start > range_end:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Параметр from должен быть не позже to")
    visible = await visible_employee_ids(conn, user)
    rows = await conn.fetch(
        ABSENCE_SELECT + """
        WHERE a.date_from<=$2 AND a.date_to>=$1
          AND ($3::uuid IS NULL OR a.employee_id=$3)
          AND ($4::uuid[] IS NULL OR a.employee_id=ANY($4::uuid[]))
          AND ($5::bigint IS NULL OR a.type_id=$5)
          AND ($6::text IS NULL OR a.status=$6)
        ORDER BY a.date_from,a.created_at
        """, range_start, range_end, employee_id, None if visible is None else list(visible), type_id, absence_status,
    )
    return [AbsenceItem(**dict(row)) for row in rows]


@router.post("/absences", response_model=list[AbsenceItem], status_code=201)
async def create_absences(
    payload: AbsenceCreate,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("timeline:view")),
) -> list[AbsenceItem]:
    employee_ids = set(payload.employee_ids)
    await ensure_employee_scope(conn, user, employee_ids)
    can_manage = "absence:manage" in user.permissions
    if not can_manage:
        if user.employee_id is None or employee_ids != {user.employee_id}:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Можно создать заявку только для себя")
        effective_status = "pending"
    else:
        effective_status = payload.status
    existing = await conn.fetchval("SELECT count(*) FROM employees WHERE id=ANY($1::uuid[])", list(employee_ids))
    if existing != len(employee_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Один из сотрудников не найден")
    type_row = await conn.fetchrow("SELECT code FROM absence_types WHERE id=$1", payload.type_id)
    if type_row is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Тип отсутствия не найден")
    if type_row["code"] == "VIOLATION" and payload.severity is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Для нарушения укажите серьёзность 1–5")
    ids: list[UUID] = []
    async with conn.transaction():
        for employee_id in employee_ids:
            absence_id = await conn.fetchval(
                """INSERT INTO absences(employee_id,type_id,date_from,date_to,minutes,reason,comment,severity,
                                          status,created_by,approved_by,approved_at)
                   VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                          CASE WHEN $9='approved' THEN $10 ELSE NULL END,
                          CASE WHEN $9='approved' THEN now() ELSE NULL END)
                   RETURNING id""",
                employee_id, payload.type_id, payload.date_from, payload.date_to, payload.minutes,
                payload.reason, payload.comment, payload.severity, effective_status, user.id,
            )
            ids.append(absence_id)
            await audit(conn, user, "absence_created", str(absence_id), {"status": effective_status})
            if effective_status == "pending":
                await conn.execute(
                    """INSERT INTO notifications(user_id,notification_type,payload_json)
                       SELECT u.id,'absence_pending',jsonb_build_object('absence_id',$1,'employee_id',$2)
                       FROM users u WHERE u.role_code IN ('manager','admin','superadmin') AND u.is_active=true""",
                    absence_id, employee_id,
                )
    rows = await conn.fetch(ABSENCE_SELECT + " WHERE a.id=ANY($1::uuid[]) ORDER BY e.full_name", ids)
    return [AbsenceItem(**dict(row)) for row in rows]


@router.patch("/absences/{absence_id}", response_model=AbsenceItem)
async def update_absence(
    absence_id: UUID,
    payload: AbsencePatch,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("timeline:view")),
) -> AbsenceItem:
    current = await get_absence(conn, absence_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    await ensure_employee_scope(conn, user, {current["employee_id"]})
    can_manage = "absence:manage" in user.permissions
    if not can_manage and (user.employee_id != current["employee_id"] or current["status"] not in {"draft", "pending"}):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Редактирование запрещено")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Нет изменений")
    date_from = changes.get("date_from", current["date_from"])
    date_to = changes.get("date_to", current["date_to"])
    if date_to < date_from:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Некорректный диапазон дат")
    values: list[Any] = []
    assignments: list[str] = []
    for key, value in changes.items():
        values.append(value); assignments.append(f"{key}=${len(values)}")
    values.append(absence_id)
    await conn.execute(f"UPDATE absences SET {','.join(assignments)},updated_at=now() WHERE id=${len(values)}", *values)
    await audit(conn, user, "absence_updated", str(absence_id), changes)
    return AbsenceItem(**dict(await get_absence(conn, absence_id)))


@router.delete("/absences/{absence_id}", status_code=204)
async def delete_absence(
    absence_id: UUID,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("timeline:view")),
) -> None:
    current = await get_absence(conn, absence_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    await ensure_employee_scope(conn, user, {current["employee_id"]})
    if "absence:manage" not in user.permissions and (
        user.employee_id != current["employee_id"] or current["status"] not in {"draft", "pending"}
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Удаление запрещено")
    await conn.execute("DELETE FROM absences WHERE id=$1", absence_id)
    await audit(conn, user, "absence_deleted", str(absence_id))


async def decide_absence(
    absence_id: UUID, decision: str, payload: AbsenceDecision, conn: asyncpg.Connection, user: CurrentUser
) -> AbsenceItem:
    current = await get_absence(conn, absence_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    await ensure_employee_scope(conn, user, {current["employee_id"]})
    if current["status"] not in {"draft", "pending"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "Решение по событию уже принято")
    if decision == "approved" and current["requires_document"] and not current["attachment_key"] and not current["reason"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Для этого типа нужен документ или его номер в причине")
    await conn.execute(
        """UPDATE absences SET status=$2,approved_by=$3,approved_at=now(),
                  comment=COALESCE($4,comment),updated_at=now() WHERE id=$1""",
        absence_id, decision, user.id, payload.comment,
    )
    await conn.execute(
        """INSERT INTO notifications(user_id,notification_type,payload_json)
           SELECT created_by,$2,jsonb_build_object('absence_id',$1,'decision',$2)
           FROM absences WHERE id=$1 AND created_by IS NOT NULL""", absence_id, f"absence_{decision}",
    )
    await audit(conn, user, f"absence_{decision}", str(absence_id))
    return AbsenceItem(**dict(await get_absence(conn, absence_id)))


@router.post("/absences/{absence_id}/approve", response_model=AbsenceItem)
async def approve_absence(
    absence_id: UUID, payload: AbsenceDecision,
    conn: asyncpg.Connection = Depends(db), user: CurrentUser = Depends(require_permission("absence:manage")),
) -> AbsenceItem:
    return await decide_absence(absence_id, "approved", payload, conn, user)


@router.post("/absences/{absence_id}/reject", response_model=AbsenceItem)
async def reject_absence(
    absence_id: UUID, payload: AbsenceDecision,
    conn: asyncpg.Connection = Depends(db), user: CurrentUser = Depends(require_permission("absence:manage")),
) -> AbsenceItem:
    return await decide_absence(absence_id, "rejected", payload, conn, user)


@router.post("/absences/{absence_id}/attachment", response_model=AbsenceItem)
async def upload_absence_attachment(
    absence_id: UUID,
    attachment: UploadFile = File(),
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("timeline:view")),
) -> AbsenceItem:
    current = await get_absence(conn, absence_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    await ensure_employee_scope(conn, user, {current["employee_id"]})
    if "absence:manage" not in user.permissions and user.employee_id != current["employee_id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Загрузка запрещена")
    if attachment.content_type not in ALLOWED_ATTACHMENTS:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Разрешены PDF, JPEG, PNG и WebP")
    content = await attachment.read(MAX_ATTACHMENT_BYTES + 1)
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Файл больше 10 МБ")
    if not has_valid_signature(attachment.content_type, content):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Сигнатура файла не соответствует MIME")
    key = str(PurePosixPath("absence-attachments", str(current["employee_id"]), f"{absence_id}-{uuid4().hex}{ALLOWED_ATTACHMENTS[attachment.content_type]}"))
    await ObjectStorage().put_bytes(key, content, attachment.content_type)
    await conn.execute("UPDATE absences SET attachment_key=$2,updated_at=now() WHERE id=$1", absence_id, key)
    await audit(conn, user, "absence_attachment_uploaded", str(absence_id), {"size": len(content)})
    return AbsenceItem(**dict(await get_absence(conn, absence_id)))


@router.get("/calendar", response_model=AbsenceCalendar)
async def absence_calendar(
    month: str = Query(pattern="^\\d{4}-\\d{2}$"),
    department_id: UUID | None = None,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("timeline:view")),
) -> AbsenceCalendar:
    try:
        year, month_number = map(int, month.split("-"))
        days = monthrange(year, month_number)[1]
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Некорректный месяц") from error
    start = date(year, month_number, 1); end = date(year, month_number, days)
    visible = await visible_employee_ids(conn, user)
    employees = await conn.fetch(
        """SELECT e.id,e.full_name,COALESCE(d.name,e.department_name) AS department_name
           FROM employees e LEFT JOIN departments d ON d.id=e.department_id
           WHERE e.status='active' AND ($1::uuid IS NULL OR e.department_id=$1)
             AND ($2::uuid[] IS NULL OR e.id=ANY($2::uuid[])) ORDER BY department_name,e.full_name""",
        department_id, None if visible is None else list(visible),
    )
    employee_ids = [row["id"] for row in employees]
    event_rows = await conn.fetch(
        ABSENCE_SELECT + " WHERE a.employee_id=ANY($1::uuid[]) AND a.date_from<=$3 AND a.date_to>=$2 ORDER BY a.date_from",
        employee_ids, start, end,
    ) if employee_ids else []
    by_employee: dict[UUID, list[AbsenceItem]] = {employee_id: [] for employee_id in employee_ids}
    for row in event_rows:
        by_employee[row["employee_id"]].append(AbsenceItem(**dict(row)))
    return AbsenceCalendar(month=month, days=days, employees=[
        CalendarEmployee(employee_id=row["id"], full_name=row["full_name"], department_name=row["department_name"], events=by_employee[row["id"]])
        for row in employees
    ])


def validate_schedule_rules(kind: str, rules: dict) -> None:
    if kind == "fixed":
        if not isinstance(rules.get("weekdays"), list) or not rules.get("start") or not rules.get("end"):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Фиксированный график требует weekdays, start и end")
        if any(day not in range(1, 8) for day in rules["weekdays"]):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Дни недели должны быть 1–7")


@router.get("/schedules", response_model=list[ScheduleItem])
async def list_schedules(
    conn: asyncpg.Connection = Depends(db), _: CurrentUser = Depends(require_permission("settings:manage")),
) -> list[ScheduleItem]:
    rows = await conn.fetch(
        """SELECT s.id,s.name,s.kind,s.rules_json AS rules,count(sa.id)::int AS assignments_count
           FROM schedules s LEFT JOIN schedule_assignments sa ON sa.schedule_id=s.id GROUP BY s.id ORDER BY s.name"""
    )
    return [ScheduleItem(**dict(row)) for row in rows]


@router.post("/schedules", response_model=ScheduleItem, status_code=201)
async def create_schedule(
    payload: ScheduleCreate, conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("settings:manage")),
) -> ScheduleItem:
    validate_schedule_rules(payload.kind, payload.rules)
    try:
        row = await conn.fetchrow(
            """INSERT INTO schedules(name,kind,rules_json) VALUES($1,$2,$3::jsonb)
               RETURNING id,name,kind,rules_json AS rules,0::int AS assignments_count""",
            payload.name.strip(), payload.kind, json.dumps(payload.rules),
        )
    except asyncpg.UniqueViolationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "График с таким названием уже существует") from error
    await audit(conn, user, "schedule_created", str(row["id"]))
    return ScheduleItem(**dict(row))


@router.delete("/schedules/{schedule_id}", status_code=204)
async def delete_schedule(
    schedule_id: UUID, conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("settings:manage")),
) -> None:
    try:
        result = await conn.execute("DELETE FROM schedules WHERE id=$1", schedule_id)
    except asyncpg.ForeignKeyViolationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "Сначала завершите назначения этого графика") from error
    if result.endswith(" 0"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "График не найден")
    await audit(conn, user, "schedule_deleted", str(schedule_id))


@router.get("/schedule-assignments", response_model=list[ScheduleAssignmentItem])
async def list_schedule_assignments(
    employee_id: UUID | None = None,
    conn: asyncpg.Connection = Depends(db), _: CurrentUser = Depends(require_permission("settings:manage")),
) -> list[ScheduleAssignmentItem]:
    rows = await conn.fetch(
        """SELECT sa.id,sa.employee_id,e.full_name AS employee_name,sa.schedule_id,s.name AS schedule_name,
                  sa.valid_from,sa.valid_to FROM schedule_assignments sa JOIN employees e ON e.id=sa.employee_id
           JOIN schedules s ON s.id=sa.schedule_id WHERE ($1::uuid IS NULL OR sa.employee_id=$1)
           ORDER BY e.full_name,sa.valid_from DESC""", employee_id,
    )
    return [ScheduleAssignmentItem(**dict(row)) for row in rows]


@router.post("/schedule-assignments", response_model=list[ScheduleAssignmentItem], status_code=201)
async def assign_schedule(
    payload: ScheduleAssignmentCreate, conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("settings:manage")),
) -> list[ScheduleAssignmentItem]:
    ids: list[UUID] = []
    async with conn.transaction():
        for employee_id in set(payload.employee_ids):
            await conn.execute(
                """UPDATE schedule_assignments SET valid_to=$2 - 1
                   WHERE employee_id=$1 AND valid_from<$2 AND (valid_to IS NULL OR valid_to>=$2)""",
                employee_id, payload.valid_from,
            )
            assignment_id = await conn.fetchval(
                """INSERT INTO schedule_assignments(employee_id,schedule_id,valid_from,valid_to)
                   VALUES($1,$2,$3,$4) RETURNING id""",
                employee_id, payload.schedule_id, payload.valid_from, payload.valid_to,
            )
            ids.append(assignment_id)
            await audit(conn, user, "schedule_assigned", str(assignment_id), {"employee_id": employee_id})
    rows = await conn.fetch(
        """SELECT sa.id,sa.employee_id,e.full_name AS employee_name,sa.schedule_id,s.name AS schedule_name,
                  sa.valid_from,sa.valid_to FROM schedule_assignments sa JOIN employees e ON e.id=sa.employee_id
           JOIN schedules s ON s.id=sa.schedule_id WHERE sa.id=ANY($1::uuid[])""", ids,
    )
    return [ScheduleAssignmentItem(**dict(row)) for row in rows]


@router.get("/holidays", response_model=list[HolidayItem])
async def list_holidays(
    year: int = Query(ge=2000, le=2200), conn: asyncpg.Connection = Depends(db),
    _: CurrentUser = Depends(require_permission("timeline:view")),
) -> list[HolidayItem]:
    rows = await conn.fetch(
        "SELECT holiday_date,name,kind FROM holidays WHERE EXTRACT(YEAR FROM holiday_date)=$1 ORDER BY holiday_date", year,
    )
    return [HolidayItem(**dict(row)) for row in rows]


@router.put("/holidays/{holiday_date}", response_model=HolidayItem)
async def upsert_holiday(
    holiday_date: date, payload: HolidayItem, conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("settings:manage")),
) -> HolidayItem:
    row = await conn.fetchrow(
        """INSERT INTO holidays(holiday_date,name,kind) VALUES($1,$2,$3)
           ON CONFLICT(holiday_date) DO UPDATE SET name=EXCLUDED.name,kind=EXCLUDED.kind
           RETURNING holiday_date,name,kind""", holiday_date, payload.name, payload.kind,
    )
    await audit(conn, user, "holiday_updated", str(holiday_date))
    return HolidayItem(**dict(row))
