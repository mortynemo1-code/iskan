import hashlib
import json
from typing import Any
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status

from .admin_schemas import (
    CategoryCreate,
    CategoryPatch,
    CategoryResponse,
    DepartmentCreate,
    DepartmentResponse,
    DeviceAdminPatch,
    DeviceAdminResponse,
    DeviceCommandRequest,
    EmployeeCreate,
    EmployeePatch,
    EmployeeResponse,
    RuleCreate,
    RulePatch,
    RuleResponse,
    RuleTestRequest,
    UpdateReleasePatch,
    WindowsAccountPatch,
    WindowsAccountResponse,
)
from .admin_validation import validate_rule_pattern
from .auth import require_permission
from .database import connection
from .storage import ObjectStorage
from .upload_validation import has_valid_signature


router = APIRouter(
    prefix="/api/v1/admin",
    tags=["admin"],
    dependencies=[Depends(require_permission("settings:manage"))],
)


async def db() -> asyncpg.Connection:
    async for conn in connection():
        yield conn


async def audit(
    conn: asyncpg.Connection,
    action: str,
    object_type: str,
    object_id: str,
    details: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO audit_log(action, object_type, object_id, details_json)
        VALUES($1, $2, $3, $4::jsonb)
        """,
        action,
        object_type,
        object_id,
        json.dumps(details or {}, default=str),
    )


async def employee_by_id(conn: asyncpg.Connection, employee_id: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT e.id, e.full_name, e.email, e.department_id, e.position_title, e.hire_date,
               COALESCE(d.name, e.department_name) AS department_name,
               e.timezone, e.planned_daily_minutes, e.status, e.created_at,
               count(dev.id)::int AS devices_count
        FROM employees e
        LEFT JOIN departments d ON d.id = e.department_id
        LEFT JOIN devices dev ON dev.employee_id = e.id
        WHERE e.id = $1
        GROUP BY e.id, d.name
        """,
        employee_id,
    )


async def category_by_id(conn: asyncpg.Connection, category_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT c.id, c.code, c.name, c.productivity, c.color, c.is_system,
               c.created_at, count(r.id)::int AS rules_count
        FROM categories c
        LEFT JOIN rules r ON r.category_id = c.id
        WHERE c.id = $1
        GROUP BY c.id
        """,
        category_id,
    )


async def rule_by_id(conn: asyncpg.Connection, rule_id: int) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT r.id, r.priority, r.match_field, r.match_type, r.pattern,
               r.category_id, c.name AS category_name, c.productivity,
               r.enabled, r.created_at
        FROM rules r
        JOIN categories c ON c.id = r.category_id
        WHERE r.id = $1
        """,
        rule_id,
    )


@router.get("/departments", response_model=list[DepartmentResponse])
async def list_departments(conn: asyncpg.Connection = Depends(db)) -> list[DepartmentResponse]:
    rows = await conn.fetch(
        """
        SELECT d.id, d.name, d.parent_id, d.created_at,
               count(e.id)::int AS employee_count
        FROM departments d
        LEFT JOIN employees e ON e.department_id = d.id AND e.status = 'active'
        GROUP BY d.id
        ORDER BY d.name
        """
    )
    return [DepartmentResponse(**dict(row)) for row in rows]


@router.post("/departments", response_model=DepartmentResponse, status_code=201)
async def create_department(
    payload: DepartmentCreate, conn: asyncpg.Connection = Depends(db)
) -> DepartmentResponse:
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO departments(name, parent_id)
            VALUES($1, $2)
            RETURNING id, name, parent_id, created_at, 0::int AS employee_count
            """,
            payload.name,
            payload.parent_id,
        )
    except asyncpg.UniqueViolationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "Отдел с таким названием уже существует") from error
    except asyncpg.ForeignKeyViolationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Родительский отдел не найден") from error
    await audit(conn, "department_created", "department", str(row["id"]), {"name": row["name"]})
    return DepartmentResponse(**dict(row))


@router.get("/employees", response_model=list[EmployeeResponse])
async def list_employees(conn: asyncpg.Connection = Depends(db)) -> list[EmployeeResponse]:
    rows = await conn.fetch(
        """
        SELECT e.id, e.full_name, e.email, e.department_id, e.position_title, e.hire_date,
               COALESCE(d.name, e.department_name) AS department_name,
               e.timezone, e.planned_daily_minutes, e.status, e.created_at,
               count(dev.id)::int AS devices_count
        FROM employees e
        LEFT JOIN departments d ON d.id = e.department_id
        LEFT JOIN devices dev ON dev.employee_id = e.id
        GROUP BY e.id, d.name
        ORDER BY (e.status = 'active') DESC, e.full_name
        """
    )
    return [EmployeeResponse(**dict(row)) for row in rows]


@router.post("/employees", response_model=EmployeeResponse, status_code=201)
async def create_employee(
    payload: EmployeeCreate, conn: asyncpg.Connection = Depends(db)
) -> EmployeeResponse:
    try:
        employee_id = await conn.fetchval(
            """
            INSERT INTO employees(
                full_name, email, department_id, department_name, position_title,
                hire_date, timezone, planned_daily_minutes
            )
            VALUES($1, $2, $3, (SELECT name FROM departments WHERE id = $3), $4, $5, $6, $7)
            RETURNING id
            """,
            payload.full_name,
            payload.email,
            payload.department_id,
            payload.position_title,
            payload.hire_date,
            payload.timezone,
            payload.planned_daily_minutes,
        )
    except asyncpg.UniqueViolationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "Сотрудник с таким email уже существует") from error
    except asyncpg.ForeignKeyViolationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Отдел не найден") from error
    await audit(conn, "employee_created", "employee", str(employee_id))
    row = await employee_by_id(conn, employee_id)
    return EmployeeResponse(**dict(row))


@router.patch("/employees/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: UUID,
    payload: EmployeePatch,
    conn: asyncpg.Connection = Depends(db),
) -> EmployeeResponse:
    changes = payload.model_dump(exclude_unset=True)
    if "full_name" in changes:
        if changes["full_name"] is None or not changes["full_name"].strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Имя не может быть пустым")
        changes["full_name"] = changes["full_name"].strip()
    if "timezone" in changes:
        if changes["timezone"] is None or not changes["timezone"].strip():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Часовой пояс не может быть пустым")
        changes["timezone"] = changes["timezone"].strip()
    if "email" in changes and changes["email"] is not None:
        changes["email"] = changes["email"].strip().lower() or None

    allowed = [
        "full_name", "email", "department_id", "position_title", "hire_date",
        "timezone", "status", "planned_daily_minutes",
    ]
    assignments: list[str] = []
    values: list[Any] = []
    for field in allowed:
        if field in changes:
            values.append(changes[field])
            assignments.append(f"{field} = ${len(values)}")
    assignments.append("updated_at = now()")
    values.append(employee_id)
    try:
        updated_id = await conn.fetchval(
            f"UPDATE employees SET {', '.join(assignments)} WHERE id = ${len(values)} RETURNING id",
            *values,
        )
        if updated_id is not None and "department_id" in changes:
            await conn.execute(
                """
                UPDATE employees
                SET department_name = (SELECT name FROM departments WHERE id = department_id)
                WHERE id = $1
                """,
                employee_id,
            )
    except asyncpg.UniqueViolationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "Сотрудник с таким email уже существует") from error
    except asyncpg.ForeignKeyViolationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Отдел не найден") from error
    if updated_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сотрудник не найден")
    await audit(conn, "employee_updated", "employee", str(employee_id), changes)
    row = await employee_by_id(conn, employee_id)
    return EmployeeResponse(**dict(row))


@router.get("/devices", response_model=list[DeviceAdminResponse])
async def list_devices(conn: asyncpg.Connection = Depends(db)) -> list[DeviceAdminResponse]:
    rows = await conn.fetch(
        """
        SELECT d.id, d.employee_id, e.full_name AS employee_name, d.hostname,
               d.os_version, d.agent_version, d.is_approved, d.last_seen,
               d.last_activity_state, d.created_at
        FROM devices d
        LEFT JOIN employees e ON e.id = d.employee_id
        ORDER BY d.is_approved, d.created_at DESC
        """
    )
    return [DeviceAdminResponse(**dict(row)) for row in rows]


@router.patch("/devices/{device_id}", response_model=DeviceAdminResponse)
async def update_device(
    device_id: UUID,
    payload: DeviceAdminPatch,
    conn: asyncpg.Connection = Depends(db),
) -> DeviceAdminResponse:
    current = await conn.fetchrow("SELECT employee_id, is_approved FROM devices WHERE id = $1", device_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Устройство не найдено")
    changes = payload.model_dump(exclude_unset=True)
    employee_id = changes.get("employee_id", current["employee_id"])
    approved = changes.get("is_approved", current["is_approved"])
    if employee_id is not None and not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM employees WHERE id=$1)", employee_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Сотрудник не найден")
    if approved and employee_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Перед подтверждением привяжите устройство к сотруднику",
        )

    assignments: list[str] = []
    values: list[Any] = []
    for field in ("employee_id", "is_approved"):
        if field in changes:
            values.append(changes[field])
            assignments.append(f"{field} = ${len(values)}")
    assignments.append("updated_at = now()")
    values.append(device_id)
    async with conn.transaction():
        await conn.execute(
            f"UPDATE devices SET {', '.join(assignments)} WHERE id = ${len(values)}",
            *values,
        )
        if "employee_id" in changes:
            await conn.execute(
                "UPDATE activity_events SET employee_id = $1 WHERE device_id = $2",
                employee_id,
                device_id,
            )
        await audit(conn, "device_updated", "device", str(device_id), changes)

    row = await conn.fetchrow(
        """
        SELECT d.id, d.employee_id, e.full_name AS employee_name, d.hostname,
               d.os_version, d.agent_version, d.is_approved, d.last_seen,
               d.last_activity_state, d.created_at
        FROM devices d
        LEFT JOIN employees e ON e.id = d.employee_id
        WHERE d.id = $1
        """,
        device_id,
    )
    return DeviceAdminResponse(**dict(row))


@router.post("/devices/{device_id}/revoke-token", status_code=202)
async def revoke_device_token(
    device_id: UUID,
    conn: asyncpg.Connection = Depends(db),
) -> dict[str, bool]:
    result = await conn.execute(
        """UPDATE devices SET token_hash=encode(digest('revoked:' || id::text || clock_timestamp()::text,'sha256'),'hex'),
                  is_approved=false,updated_at=now() WHERE id=$1""",
        device_id,
    )
    if result.endswith(" 0"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Устройство не найдено")
    await audit(conn, "device_token_revoked", "device", str(device_id))
    return {"revoked": True}


@router.post("/devices/{device_id}/commands", status_code=202)
async def send_device_command(
    device_id: UUID,
    payload: DeviceCommandRequest,
    conn: asyncpg.Connection = Depends(db),
) -> dict[str, str]:
    if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM devices WHERE id=$1 AND is_approved=true)", device_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Подтверждённое устройство не найдено")
    command_id = await conn.fetchval(
        "INSERT INTO agent_commands(device_id,command,payload_json) VALUES($1,$2,'{}'::jsonb) RETURNING id",
        device_id, payload.command,
    )
    await audit(conn, "device_command_requested", "device", str(device_id), {"command": payload.command, "command_id": command_id})
    return {"id": str(command_id), "status": "pending"}


@router.get("/diagnostics")
async def list_agent_diagnostics(conn: asyncpg.Connection = Depends(db)) -> list[dict]:
    rows = await conn.fetch(
        """SELECT a.id,a.device_id,d.hostname,a.size_bytes,a.reason,a.created_at
           FROM agent_diagnostics a JOIN devices d ON d.id=a.device_id ORDER BY a.created_at DESC LIMIT 200"""
    )
    return [dict(row) | {"download_url": f"/api/v1/admin/diagnostics/{row['id']}/download"} for row in rows]


@router.get("/diagnostics/{diagnostic_id}/download")
async def download_agent_diagnostics(diagnostic_id: UUID, conn: asyncpg.Connection = Depends(db)) -> Response:
    key = await conn.fetchval("SELECT storage_key FROM agent_diagnostics WHERE id=$1", diagnostic_id)
    if key is None: raise HTTPException(status.HTTP_404_NOT_FOUND, "Диагностика не найдена")
    content = await ObjectStorage().get_bytes(key)
    return Response(content, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="diagnostics-{diagnostic_id}.zip"'})


@router.get("/windows-accounts", response_model=list[WindowsAccountResponse])
async def list_windows_accounts(conn: asyncpg.Connection = Depends(db)) -> list[WindowsAccountResponse]:
    rows = await conn.fetch(
        """SELECT wa.id,wa.device_id,d.hostname,wa.sid,wa.username,wa.employee_id,e.full_name AS employee_name,
                  count(a.id) FILTER(WHERE a.is_quarantined)::int AS quarantined_events,wa.created_at
           FROM windows_accounts wa JOIN devices d ON d.id=wa.device_id LEFT JOIN employees e ON e.id=wa.employee_id
           LEFT JOIN activity_events a ON a.device_id=wa.device_id AND a.windows_sid=wa.sid
           GROUP BY wa.id,d.hostname,e.full_name ORDER BY (wa.employee_id IS NULL) DESC,wa.created_at DESC"""
    )
    return [WindowsAccountResponse(**dict(row)) for row in rows]


@router.patch("/windows-accounts/{account_id}", response_model=WindowsAccountResponse)
async def map_windows_account(
    account_id: UUID,
    payload: WindowsAccountPatch,
    conn: asyncpg.Connection = Depends(db),
) -> WindowsAccountResponse:
    if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM employees WHERE id=$1)", payload.employee_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Сотрудник не найден")
    async with conn.transaction():
        account = await conn.fetchrow(
            "UPDATE windows_accounts SET employee_id=$2 WHERE id=$1 RETURNING device_id,sid",
            account_id, payload.employee_id,
        )
        if account is None: raise HTTPException(status.HTTP_404_NOT_FOUND, "Учётная запись Windows не найдена")
        await conn.execute(
            """UPDATE activity_events SET employee_id=$3,is_quarantined=false
               WHERE device_id=$1 AND windows_sid=$2 AND is_quarantined=true""",
            account["device_id"], account["sid"], payload.employee_id,
        )
        await audit(conn, "windows_account_mapped", "windows_account", str(account_id), {"employee_id": payload.employee_id})
    row = await conn.fetchrow(
        """SELECT wa.id,wa.device_id,d.hostname,wa.sid,wa.username,wa.employee_id,e.full_name AS employee_name,
                  count(a.id) FILTER(WHERE a.is_quarantined)::int AS quarantined_events,wa.created_at
           FROM windows_accounts wa JOIN devices d ON d.id=wa.device_id LEFT JOIN employees e ON e.id=wa.employee_id
           LEFT JOIN activity_events a ON a.device_id=wa.device_id AND a.windows_sid=wa.sid
           WHERE wa.id=$1 GROUP BY wa.id,d.hostname,e.full_name""", account_id,
    )
    return WindowsAccountResponse(**dict(row))


@router.get("/update-releases")
async def list_update_releases(conn: asyncpg.Connection = Depends(db)) -> list[dict]:
    rows = await conn.fetch(
        """SELECT id,version,sha256,rollout_percent,minimum_agent_version,
                  maintenance_start_hour,maintenance_end_hour,is_active,created_at
           FROM update_releases ORDER BY created_at DESC"""
    )
    return [dict(row) for row in rows]


@router.post("/update-releases", status_code=201)
async def create_update_release(
    package: UploadFile = File(...),
    version: str = Form(..., min_length=3, max_length=32, pattern=r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$"),
    rollout_percent: int = Form(default=5, ge=0, le=100),
    maintenance_start_hour: int = Form(default=1, ge=0, le=23),
    maintenance_end_hour: int = Form(default=5, ge=0, le=23),
    conn: asyncpg.Connection = Depends(db),
) -> dict:
    content = await package.read(250 * 1024 * 1024 + 1)
    if len(content) > 250 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "MSI превышает 250 МБ")
    if not has_valid_signature("application/x-msi", content):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Ожидается MSI-пакет")
    checksum = hashlib.sha256(content).hexdigest()
    key = f"updates/workforce-agent-{version}.msi"
    await ObjectStorage().put_bytes(key, content, "application/x-msi")
    try:
        row = await conn.fetchrow(
            """INSERT INTO update_releases(version,storage_key,sha256,rollout_percent,maintenance_start_hour,maintenance_end_hour)
               VALUES($1,$2,$3,$4,$5,$6)
               RETURNING id,version,sha256,rollout_percent,is_active,created_at""",
            version, key, checksum, rollout_percent, maintenance_start_hour, maintenance_end_hour,
        )
    except asyncpg.UniqueViolationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "Такая версия уже загружена") from error
    await audit(conn, "update_release_created", "update_release", str(row["id"]), {"version": version, "sha256": checksum})
    return dict(row)


@router.patch("/update-releases/{release_id}")
async def patch_update_release(
    release_id: UUID,
    payload: UpdateReleasePatch,
    conn: asyncpg.Connection = Depends(db),
) -> dict:
    row = await conn.fetchrow(
        """UPDATE update_releases SET rollout_percent=COALESCE($2,rollout_percent),is_active=COALESCE($3,is_active)
           WHERE id=$1 RETURNING id,version,sha256,rollout_percent,is_active,created_at""",
        release_id, payload.rollout_percent, payload.is_active,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Релиз не найден")
    await audit(conn, "update_release_changed", "update_release", str(release_id), payload.model_dump(exclude_unset=True))
    return dict(row)


@router.get("/categories", response_model=list[CategoryResponse])
async def list_categories(conn: asyncpg.Connection = Depends(db)) -> list[CategoryResponse]:
    rows = await conn.fetch(
        """
        SELECT c.id, c.code, c.name, c.productivity, c.color, c.is_system,
               c.created_at, count(r.id)::int AS rules_count
        FROM categories c
        LEFT JOIN rules r ON r.category_id = c.id
        GROUP BY c.id
        ORDER BY c.is_system DESC, c.name
        """
    )
    return [CategoryResponse(**dict(row)) for row in rows]


@router.post("/categories", response_model=CategoryResponse, status_code=201)
async def create_category(
    payload: CategoryCreate, conn: asyncpg.Connection = Depends(db)
) -> CategoryResponse:
    try:
        category_id = await conn.fetchval(
            """
            INSERT INTO categories(code, name, productivity, color)
            VALUES($1, $2, $3, $4)
            RETURNING id
            """,
            payload.code,
            payload.name.strip(),
            payload.productivity,
            payload.color,
        )
    except asyncpg.UniqueViolationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "Категория с таким кодом уже существует") from error
    await audit(conn, "category_created", "category", str(category_id))
    row = await category_by_id(conn, category_id)
    return CategoryResponse(**dict(row))


@router.patch("/categories/{category_id}", response_model=CategoryResponse)
async def update_category(
    category_id: int,
    payload: CategoryPatch,
    conn: asyncpg.Connection = Depends(db),
) -> CategoryResponse:
    current = await conn.fetchrow("SELECT is_system FROM categories WHERE id = $1", category_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Категория не найдена")
    changes = payload.model_dump(exclude_unset=True)
    if current["is_system"] and "code" in changes:
        raise HTTPException(status.HTTP_409_CONFLICT, "Код системной категории изменять нельзя")
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    assignments: list[str] = []
    values: list[Any] = []
    for field in ("code", "name", "productivity", "color"):
        if field in changes:
            values.append(changes[field])
            assignments.append(f"{field} = ${len(values)}")
    assignments.append("updated_at = now()")
    values.append(category_id)
    try:
        await conn.execute(
            f"UPDATE categories SET {', '.join(assignments)} WHERE id = ${len(values)}",
            *values,
        )
    except asyncpg.UniqueViolationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "Категория с таким кодом уже существует") from error
    await audit(conn, "category_updated", "category", str(category_id), changes)
    row = await category_by_id(conn, category_id)
    return CategoryResponse(**dict(row))


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(category_id: int, conn: asyncpg.Connection = Depends(db)) -> None:
    row = await category_by_id(conn, category_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Категория не найдена")
    if row["is_system"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Системную категорию удалить нельзя")
    if row["rules_count"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Сначала удалите правила этой категории")
    await conn.execute("DELETE FROM categories WHERE id = $1", category_id)
    await audit(conn, "category_deleted", "category", str(category_id))


@router.get("/rules", response_model=list[RuleResponse])
async def list_rules(conn: asyncpg.Connection = Depends(db)) -> list[RuleResponse]:
    rows = await conn.fetch(
        """
        SELECT r.id, r.priority, r.match_field, r.match_type, r.pattern,
               r.category_id, c.name AS category_name, c.productivity,
               r.enabled, r.created_at
        FROM rules r
        JOIN categories c ON c.id = r.category_id
        ORDER BY r.priority, r.id
        """
    )
    return [RuleResponse(**dict(row)) for row in rows]


@router.post("/rules", response_model=RuleResponse, status_code=201)
async def create_rule(payload: RuleCreate, conn: asyncpg.Connection = Depends(db)) -> RuleResponse:
    if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM categories WHERE id=$1)", payload.category_id):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Категория не найдена")
    rule_id = await conn.fetchval(
        """
        INSERT INTO rules(priority, match_field, match_type, pattern, category_id, enabled)
        VALUES($1, $2, $3, $4, $5, $6)
        RETURNING id
        """,
        payload.priority,
        payload.match_field,
        payload.match_type,
        payload.pattern,
        payload.category_id,
        payload.enabled,
    )
    await audit(conn, "rule_created", "rule", str(rule_id))
    row = await rule_by_id(conn, rule_id)
    return RuleResponse(**dict(row))


@router.patch("/rules/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: int,
    payload: RulePatch,
    conn: asyncpg.Connection = Depends(db),
) -> RuleResponse:
    current = await conn.fetchrow("SELECT * FROM rules WHERE id = $1", rule_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Правило не найдено")
    changes = payload.model_dump(exclude_unset=True)
    match_type = changes.get("match_type", current["match_type"])
    pattern = changes.get("pattern", current["pattern"])
    try:
        changes["pattern"] = validate_rule_pattern(match_type, pattern)
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error)) from error
    if "category_id" in changes and not await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM categories WHERE id=$1)", changes["category_id"]
    ):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Категория не найдена")
    assignments: list[str] = []
    values: list[Any] = []
    for field in ("priority", "match_field", "match_type", "pattern", "category_id", "enabled"):
        if field in changes:
            values.append(changes[field])
            assignments.append(f"{field} = ${len(values)}")
    assignments.append("updated_at = now()")
    values.append(rule_id)
    await conn.execute(f"UPDATE rules SET {', '.join(assignments)} WHERE id = ${len(values)}", *values)
    await audit(conn, "rule_updated", "rule", str(rule_id), changes)
    row = await rule_by_id(conn, rule_id)
    return RuleResponse(**dict(row))


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, conn: asyncpg.Connection = Depends(db)) -> None:
    deleted = await conn.fetchval("DELETE FROM rules WHERE id = $1 RETURNING id", rule_id)
    if deleted is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Правило не найдено")
    await audit(conn, "rule_deleted", "rule", str(rule_id))


@router.post("/rules/test")
async def test_rule(payload: RuleTestRequest, conn: asyncpg.Connection = Depends(db)) -> dict[str, int]:
    fields = {
        "process_name": "COALESCE(process_name,'')",
        "window_title": "COALESCE(window_title,'')",
        "url_domain": "COALESCE(url_domain,'')",
        "url_full": "COALESCE(url_domain,'') || COALESCE(url_path,'')",
        "file_path": "COALESCE(process_name,'')",
    }
    value = fields[payload.match_field]
    if payload.match_type == "exact": predicate, pattern = f"lower({value})=lower($1)", payload.pattern
    elif payload.match_type == "contains": predicate, pattern = f"strpos(lower({value}),lower($1))>0", payload.pattern
    elif payload.match_type == "regex": predicate, pattern = f"{value} ~* $1", payload.pattern
    else:
        wildcard = payload.pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("*", "%").replace("?", "_")
        predicate, pattern = f"lower({value}) LIKE lower($1) ESCAPE '\\\\'", wildcard
    row = await conn.fetchrow(
        f"""SELECT count(*)::int AS events,COALESCE(sum(duration_sec),0)::bigint AS duration_sec
             FROM activity_events WHERE ts_start>=now()-($2*interval '1 day') AND ({predicate})""",
        pattern, payload.days,
    )
    return dict(row)


@router.post("/rules/reclassify", status_code=202)
async def start_reclassification(days: int = 30, conn: asyncpg.Connection = Depends(db)) -> dict[str, str]:
    if days < 1 or days > 365:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Период должен быть от 1 до 365 дней")
    running = await conn.fetchval("SELECT id FROM reclassification_jobs WHERE status IN ('queued','running') LIMIT 1")
    if running:
        raise HTTPException(status.HTTP_409_CONFLICT, "Пересчёт уже выполняется")
    job_id = await conn.fetchval("INSERT INTO reclassification_jobs(days) VALUES($1) RETURNING id", days)
    await audit(conn, "reclassification_started", "reclassification_job", str(job_id), {"days": days})
    return {"id": str(job_id), "status": "queued"}


@router.get("/rules/reclassify/{job_id}")
async def reclassification_status(job_id: UUID, conn: asyncpg.Connection = Depends(db)) -> dict:
    row = await conn.fetchrow("SELECT * FROM reclassification_jobs WHERE id=$1", job_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена")
    return dict(row)
