from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import ipaddress
import json
from typing import Annotated, Any, Callable
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status

from .auth_schemas import (
    AuthResponse,
    LoginRequest,
    RefreshResponse,
    RolePermissionsPatch,
    RoleResponse,
    TotpConfirmRequest,
    UserAdminCreate,
    UserAdminPatch,
    UserAdminResponse,
    UserInfo,
)
from .config import Settings, get_settings
from .database import connection
from .security import (
    TokenError,
    decode_token,
    encode_token,
    generate_totp_secret,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    totp_uri,
    verify_password,
    verify_totp,
)


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["users"])
ACCESS_COOKIE = "wm_access"
REFRESH_COOKIE = "wm_refresh"
ADMIN_2FA_ROLES = {"admin", "superadmin"}
LOCKOUT_MINUTES = 15


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    login: str
    display_name: str
    role: str
    employee_id: UUID | None
    scope_type: str
    permissions: frozenset[str]

    def to_info(self) -> UserInfo:
        return UserInfo(
            id=self.id,
            login=self.login,
            display_name=self.display_name,
            role=self.role,
            employee_id=self.employee_id,
            scope_type=self.scope_type,
            permissions=sorted(self.permissions),
        )


async def db() -> asyncpg.Connection:
    async for conn in connection():
        yield conn


async def _auth_audit(
    conn: asyncpg.Connection,
    action: str,
    user_id: UUID,
    details: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO audit_log(action, object_type, object_id, details_json)
        VALUES($1, 'user', $2, $3::jsonb)
        """,
        action,
        str(user_id),
        json.dumps(details or {}, default=str),
    )


def _client_ip(request: Request) -> str | None:
    if request.client is None:
        return None
    try:
        return str(ipaddress.ip_address(request.client.host))
    except ValueError:
        return None


async def load_current_user(conn: asyncpg.Connection, user_id: UUID) -> CurrentUser | None:
    row = await conn.fetchrow(
        """
        SELECT u.id, u.login, u.display_name, u.role_code, u.employee_id, u.scope_type,
               u.is_active, array_remove(array_agg(rp.permission_code), NULL) AS permissions
        FROM users u
        LEFT JOIN role_permissions rp ON rp.role_code = u.role_code
        WHERE u.id = $1
        GROUP BY u.id
        """,
        user_id,
    )
    if row is None or not row["is_active"]:
        return None
    return CurrentUser(
        id=row["id"],
        login=row["login"],
        display_name=row["display_name"],
        role=row["role_code"],
        employee_id=row["employee_id"],
        scope_type=row["scope_type"],
        permissions=frozenset(row["permissions"] or []),
    )


async def authenticate_access_token(
    conn: asyncpg.Connection, token: str, settings: Settings
) -> CurrentUser:
    try:
        claims = decode_token(token, settings.jwt_secret, settings.jwt_issuer, "access")
        user_id = UUID(claims["sub"])
    except (TokenError, KeyError, ValueError) as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия недействительна") from error
    user = await load_current_user(conn, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь отключён или удалён")
    return user


async def current_user(
    request: Request,
    conn: asyncpg.Connection = Depends(db),
    settings: Settings = Depends(get_settings),
) -> CurrentUser:
    authorization = request.headers.get("Authorization")
    token = authorization[7:] if authorization and authorization.startswith("Bearer ") else request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется вход в систему")
    return await authenticate_access_token(conn, token, settings)


def require_permission(permission: str) -> Callable[..., Any]:
    async def dependency(user: CurrentUser = Depends(current_user)) -> CurrentUser:
        if permission not in user.permissions:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user

    return dependency


async def visible_employee_ids(conn: asyncpg.Connection, user: CurrentUser) -> set[UUID] | None:
    if user.scope_type == "organization":
        return None
    visible: set[UUID] = set()
    if user.employee_id is not None:
        visible.add(user.employee_id)
    explicit = await conn.fetch("SELECT employee_id FROM user_employee_scope WHERE user_id=$1", user.id)
    visible.update(row["employee_id"] for row in explicit)
    if user.scope_type == "department":
        department_rows = await conn.fetch(
            """
            WITH RECURSIVE visible_departments AS (
                SELECT department_id AS id FROM user_department_scope WHERE user_id=$1
                UNION
                SELECT d.id FROM departments d JOIN visible_departments vd ON d.parent_id=vd.id
            )
            SELECT e.id FROM employees e JOIN visible_departments vd ON e.department_id=vd.id
            """,
            user.id,
        )
        visible.update(row["id"] for row in department_rows)
    return visible


def _set_auth_cookies(response: Response, access: str, refresh: str, settings: Settings) -> None:
    common = {"httponly": True, "secure": settings.auth_cookie_secure, "samesite": "strict"}
    response.set_cookie(
        ACCESS_COOKIE,
        access,
        max_age=settings.access_token_minutes * 60,
        path="/",
        **common,
    )
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=settings.refresh_token_days * 86_400,
        path="/api/v1/auth",
        **common,
    )


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/", secure=settings.auth_cookie_secure, samesite="strict")
    response.delete_cookie(
        REFRESH_COOKIE,
        path="/api/v1/auth",
        secure=settings.auth_cookie_secure,
        samesite="strict",
    )


async def _create_session(
    conn: asyncpg.Connection,
    user: CurrentUser,
    request: Request,
    response: Response,
    settings: Settings,
    family_id: UUID | None = None,
    replaces_session_id: UUID | None = None,
) -> AuthResponse:
    session_id = uuid4()
    family_id = family_id or uuid4()
    access_lifetime = timedelta(minutes=settings.access_token_minutes)
    refresh_lifetime = timedelta(days=settings.refresh_token_days)
    access = encode_token({"sub": str(user.id)}, settings.jwt_secret, settings.jwt_issuer, access_lifetime, "access")
    refresh = encode_token(
        {"sub": str(user.id), "sid": str(session_id), "fid": str(family_id)},
        settings.jwt_secret,
        settings.jwt_issuer,
        refresh_lifetime,
        "refresh",
    )
    await conn.execute(
        """
        INSERT INTO refresh_sessions(id, family_id, user_id, token_hash, expires_at, ip_address, user_agent)
        VALUES($1, $2, $3, $4, now() + $5::interval, $6, $7)
        """,
        session_id,
        family_id,
        user.id,
        hash_refresh_token(refresh, settings.jwt_secret),
        refresh_lifetime,
        _client_ip(request),
        request.headers.get("User-Agent", "")[:500],
    )
    if replaces_session_id is not None:
        await conn.execute(
            "UPDATE refresh_sessions SET revoked_at=now(), replaced_by=$1 WHERE id=$2",
            session_id,
            replaces_session_id,
        )
    _set_auth_cookies(response, access, refresh, settings)
    return AuthResponse(
        status="AUTHENTICATED",
        access_token=access,
        expires_in=settings.access_token_minutes * 60,
        user=user.to_info(),
    )


async def _record_login_failure(conn: asyncpg.Connection, user_id: UUID) -> None:
    await conn.execute(
        """
        UPDATE users
        SET failed_login_attempts = failed_login_attempts + 1,
            locked_until = CASE WHEN failed_login_attempts + 1 >= 5
                THEN now() + interval '15 minutes' ELSE locked_until END,
            updated_at = now()
        WHERE id=$1
        """,
        user_id,
    )
    await _auth_audit(conn, "auth_login_failed", user_id)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    conn: asyncpg.Connection = Depends(db),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    row = await conn.fetchrow("SELECT * FROM users WHERE lower(login)=$1", payload.login)
    if row is None or not row["is_active"]:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")
    now = datetime.now(UTC)
    if row["locked_until"] and row["locked_until"] > now:
        raise HTTPException(status.HTTP_423_LOCKED, "Вход временно заблокирован после пяти ошибок")
    if not verify_password(row["password_hash"], payload.password):
        await _record_login_failure(conn, row["id"])
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный логин или пароль")

    if row["role_code"] in ADMIN_2FA_ROLES:
        secret = row["totp_secret"]
        if not secret:
            secret = generate_totp_secret()
            await conn.execute("UPDATE users SET totp_secret=$1, updated_at=now() WHERE id=$2", secret, row["id"])
        if row["totp_confirmed_at"] is None:
            setup_token = encode_token(
                {"sub": str(row["id"])},
                settings.jwt_secret,
                settings.jwt_issuer,
                timedelta(minutes=5),
                "totp_setup",
            )
            return AuthResponse(
                status="TOTP_SETUP_REQUIRED",
                setup_token=setup_token,
                totp_secret=secret,
                totp_uri=totp_uri(secret, row["login"], settings.jwt_issuer),
            )
        if payload.totp_code is None:
            return AuthResponse(status="TOTP_REQUIRED")
        if not verify_totp(secret, payload.totp_code):
            await _record_login_failure(conn, row["id"])
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный одноразовый код")

    if password_needs_rehash(row["password_hash"]):
        await conn.execute("UPDATE users SET password_hash=$1 WHERE id=$2", hash_password(payload.password), row["id"])
    await conn.execute(
        "UPDATE users SET failed_login_attempts=0, locked_until=NULL, last_login_at=now() WHERE id=$1",
        row["id"],
    )
    await _auth_audit(conn, "auth_login_succeeded", row["id"], {"ip": _client_ip(request)})
    user = await load_current_user(conn, row["id"])
    return await _create_session(conn, user, request, response, settings)


@router.post("/totp/confirm", response_model=AuthResponse)
async def confirm_totp(
    payload: TotpConfirmRequest,
    request: Request,
    response: Response,
    conn: asyncpg.Connection = Depends(db),
    settings: Settings = Depends(get_settings),
) -> AuthResponse:
    try:
        claims = decode_token(payload.setup_token, settings.jwt_secret, settings.jwt_issuer, "totp_setup")
        user_id = UUID(claims["sub"])
    except (TokenError, KeyError, ValueError) as error:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Настройка 2FA устарела") from error
    row = await conn.fetchrow("SELECT * FROM users WHERE id=$1 AND is_active=true", user_id)
    if row is not None and row["locked_until"] and row["locked_until"] > datetime.now(UTC):
        raise HTTPException(status.HTTP_423_LOCKED, "Вход временно заблокирован после пяти ошибок")
    if row is None or not row["totp_secret"] or not verify_totp(row["totp_secret"], payload.code):
        if row is not None:
            await _record_login_failure(conn, row["id"])
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный одноразовый код")
    await conn.execute(
        """
        UPDATE users SET totp_confirmed_at=COALESCE(totp_confirmed_at, now()),
                         failed_login_attempts=0, locked_until=NULL, last_login_at=now()
        WHERE id=$1
        """,
        user_id,
    )
    await _auth_audit(conn, "auth_totp_enabled", user_id, {"ip": _client_ip(request)})
    user = await load_current_user(conn, user_id)
    return await _create_session(conn, user, request, response, settings)


@router.post("/refresh", response_model=RefreshResponse)
async def refresh(
    request: Request,
    response: Response,
    refresh_cookie: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
    conn: asyncpg.Connection = Depends(db),
    settings: Settings = Depends(get_settings),
) -> RefreshResponse:
    if not refresh_cookie:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh-токен отсутствует")
    try:
        claims = decode_token(refresh_cookie, settings.jwt_secret, settings.jwt_issuer, "refresh")
        session_id = UUID(claims["sid"])
        family_id = UUID(claims["fid"])
        user_id = UUID(claims["sub"])
    except (TokenError, KeyError, ValueError) as error:
        _clear_auth_cookies(response, settings)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh-токен недействителен") from error
    session = await conn.fetchrow("SELECT * FROM refresh_sessions WHERE id=$1", session_id)
    token_hash = hash_refresh_token(refresh_cookie, settings.jwt_secret)
    if session is None or session["user_id"] != user_id or session["family_id"] != family_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh-сессия не найдена")
    if session["revoked_at"] is not None or not hmac_compare(session["token_hash"], token_hash):
        await conn.execute("UPDATE refresh_sessions SET revoked_at=COALESCE(revoked_at, now()) WHERE family_id=$1", family_id)
        _clear_auth_cookies(response, settings)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Обнаружено повторное использование refresh-токена")
    if session["expires_at"] <= datetime.now(UTC):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh-сессия истекла")
    user = await load_current_user(conn, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь отключён")
    async with conn.transaction():
        result = await _create_session(
            conn,
            user,
            request,
            response,
            settings,
            family_id,
            replaces_session_id=session_id,
        )
    return RefreshResponse(access_token=result.access_token, expires_in=result.expires_in, user=result.user)


def hmac_compare(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    refresh_cookie: Annotated[str | None, Cookie(alias=REFRESH_COOKIE)] = None,
    conn: asyncpg.Connection = Depends(db),
    settings: Settings = Depends(get_settings),
) -> None:
    if refresh_cookie:
        try:
            claims = decode_token(refresh_cookie, settings.jwt_secret, settings.jwt_issuer, "refresh")
            await conn.execute("UPDATE refresh_sessions SET revoked_at=COALESCE(revoked_at, now()) WHERE id=$1", UUID(claims["sid"]))
        except (TokenError, KeyError, ValueError):
            pass
    _clear_auth_cookies(response, settings)


@router.get("/me", response_model=UserInfo)
async def me(user: CurrentUser = Depends(current_user)) -> UserInfo:
    return user.to_info()


async def ensure_bootstrap_admin(settings: Settings) -> None:
    if not settings.bootstrap_admin_login or not settings.bootstrap_admin_password:
        return
    async for conn in connection():
        if await conn.fetchval("SELECT EXISTS(SELECT 1 FROM users)"):
            return
        password_hash = hash_password(settings.bootstrap_admin_password)
        await conn.execute(
            """
            INSERT INTO users(login, display_name, password_hash, role_code, scope_type)
            VALUES($1, $2, $3, 'superadmin', 'organization')
            """,
            settings.bootstrap_admin_login.strip().lower(),
            settings.bootstrap_admin_name.strip(),
            password_hash,
        )
        user_id = await conn.fetchval("SELECT id FROM users WHERE lower(login)=$1", settings.bootstrap_admin_login.strip().lower())
        await _auth_audit(conn, "bootstrap_superadmin_created", user_id)


async def _user_admin_row(conn: asyncpg.Connection, user_id: UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """
        SELECT u.id, u.login, u.display_name, u.role_code, r.name AS role_name,
               u.employee_id, e.full_name AS employee_name, u.scope_type, u.is_active,
               (u.totp_confirmed_at IS NOT NULL) AS totp_enabled,
               COALESCE((SELECT array_agg(department_id) FROM user_department_scope WHERE user_id=u.id), '{}') AS department_ids,
               COALESCE((SELECT array_agg(employee_id) FROM user_employee_scope WHERE user_id=u.id), '{}') AS employee_ids
        FROM users u JOIN roles r ON r.code=u.role_code
        LEFT JOIN employees e ON e.id=u.employee_id
        WHERE u.id=$1
        """,
        user_id,
    )


@admin_router.get("/roles", response_model=list[RoleResponse])
async def list_roles(
    _: CurrentUser = Depends(require_permission("users:manage")),
    conn: asyncpg.Connection = Depends(db),
) -> list[RoleResponse]:
    rows = await conn.fetch(
        """
        SELECT r.code, r.name, array_remove(array_agg(rp.permission_code ORDER BY rp.permission_code), NULL) AS permissions
        FROM roles r LEFT JOIN role_permissions rp ON rp.role_code=r.code
        GROUP BY r.code ORDER BY r.code
        """
    )
    return [RoleResponse(code=row["code"], name=row["name"], permissions=row["permissions"] or []) for row in rows]


@admin_router.patch("/roles/{role_code}", response_model=RoleResponse)
async def update_role_permissions(
    role_code: str,
    payload: RolePermissionsPatch,
    actor: CurrentUser = Depends(require_permission("users:manage")),
    conn: asyncpg.Connection = Depends(db),
) -> RoleResponse:
    role = await conn.fetchrow("SELECT code, name FROM roles WHERE code=$1", role_code)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Роль не найдена")
    if role_code == "superadmin" and actor.role != "superadmin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только superadmin может менять эту роль")
    requested = set(payload.permissions)
    known = set(await conn.fetchval("SELECT COALESCE(array_agg(code), '{}') FROM permissions"))
    unknown = requested - known
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Неизвестные права: {', '.join(sorted(unknown))}")
    if role_code == "superadmin" and not {"users:manage", "settings:manage", "audit:view"}.issubset(requested):
        raise HTTPException(status.HTTP_409_CONFLICT, "У superadmin должны оставаться права управления и аудита")
    async with conn.transaction():
        await conn.execute("DELETE FROM role_permissions WHERE role_code=$1", role_code)
        await conn.executemany(
            "INSERT INTO role_permissions(role_code, permission_code) VALUES($1, $2)",
            [(role_code, permission) for permission in sorted(requested)],
        )
        await conn.execute(
            """
            INSERT INTO audit_log(action, object_type, object_id, details_json)
            VALUES('role_permissions_updated', 'role', $1, jsonb_build_object('permissions', $2::text[]))
            """,
            role_code,
            sorted(requested),
        )
    return RoleResponse(code=role["code"], name=role["name"], permissions=sorted(requested))


@admin_router.get("/users", response_model=list[UserAdminResponse])
async def list_users(
    _: CurrentUser = Depends(require_permission("users:manage")),
    conn: asyncpg.Connection = Depends(db),
) -> list[UserAdminResponse]:
    ids = await conn.fetch("SELECT id FROM users ORDER BY is_active DESC, display_name")
    return [UserAdminResponse(**dict(await _user_admin_row(conn, row["id"]))) for row in ids]


async def _replace_user_scopes(
    conn: asyncpg.Connection,
    user_id: UUID,
    department_ids: list[UUID] | None,
    employee_ids: list[UUID] | None,
) -> None:
    if department_ids is not None:
        await conn.execute("DELETE FROM user_department_scope WHERE user_id=$1", user_id)
        await conn.executemany(
            "INSERT INTO user_department_scope(user_id, department_id) VALUES($1, $2)",
            [(user_id, item) for item in department_ids],
        )
    if employee_ids is not None:
        await conn.execute("DELETE FROM user_employee_scope WHERE user_id=$1", user_id)
        await conn.executemany(
            "INSERT INTO user_employee_scope(user_id, employee_id) VALUES($1, $2)",
            [(user_id, item) for item in employee_ids],
        )


@admin_router.post("/users", response_model=UserAdminResponse, status_code=201)
async def create_user(
    payload: UserAdminCreate,
    actor: CurrentUser = Depends(require_permission("users:manage")),
    conn: asyncpg.Connection = Depends(db),
) -> UserAdminResponse:
    if payload.role_code == "superadmin" and actor.role != "superadmin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только superadmin может создавать superadmin")
    try:
        async with conn.transaction():
            user_id = await conn.fetchval(
                """
                INSERT INTO users(login, display_name, password_hash, role_code, employee_id, scope_type)
                VALUES($1, $2, $3, $4, $5, $6) RETURNING id
                """,
                payload.login,
                payload.display_name.strip(),
                hash_password(payload.password),
                payload.role_code,
                payload.employee_id,
                payload.scope_type,
            )
            await _replace_user_scopes(conn, user_id, payload.department_ids, payload.employee_ids)
    except asyncpg.UniqueViolationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "Логин или сотрудник уже используется") from error
    except asyncpg.ForeignKeyViolationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Роль, сотрудник или отдел не найден") from error
    await _auth_audit(conn, "user_created", user_id, {"actor_id": actor.id, "role": payload.role_code})
    row = await _user_admin_row(conn, user_id)
    return UserAdminResponse(**dict(row))


@admin_router.patch("/users/{user_id}", response_model=UserAdminResponse)
async def update_user(
    user_id: UUID,
    payload: UserAdminPatch,
    actor: CurrentUser = Depends(require_permission("users:manage")),
    conn: asyncpg.Connection = Depends(db),
) -> UserAdminResponse:
    current = await conn.fetchrow("SELECT role_code FROM users WHERE id=$1", user_id)
    if current is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    target_role = payload.role_code or current["role_code"]
    if (current["role_code"] == "superadmin" or target_role == "superadmin") and actor.role != "superadmin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Только superadmin может изменять superadmin")
    changes = payload.model_dump(exclude_unset=True)
    if user_id == actor.id and changes.get("is_active") is False:
        raise HTTPException(status.HTTP_409_CONFLICT, "Нельзя отключить собственную учётную запись")
    department_ids = changes.pop("department_ids", None)
    employee_ids = changes.pop("employee_ids", None)
    if "password" in changes:
        changes["password_hash"] = hash_password(changes.pop("password"))
        changes["totp_secret"] = None
        changes["totp_confirmed_at"] = None
    allowed = ["display_name", "password_hash", "role_code", "employee_id", "scope_type", "is_active", "totp_secret", "totp_confirmed_at"]
    values: list[Any] = []
    assignments: list[str] = []
    for field in allowed:
        if field in changes:
            values.append(changes[field])
            assignments.append(f"{field}=${len(values)}")
    assignments.append("updated_at=now()")
    values.append(user_id)
    try:
        async with conn.transaction():
            await conn.execute(f"UPDATE users SET {', '.join(assignments)} WHERE id=${len(values)}", *values)
            await _replace_user_scopes(conn, user_id, department_ids, employee_ids)
            if changes.get("is_active") is False or "password_hash" in changes:
                await conn.execute("UPDATE refresh_sessions SET revoked_at=COALESCE(revoked_at, now()) WHERE user_id=$1", user_id)
    except asyncpg.UniqueViolationError as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "Сотрудник уже связан с другим пользователем") from error
    except asyncpg.ForeignKeyViolationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Роль, сотрудник или отдел не найден") from error
    await _auth_audit(conn, "user_updated", user_id, {"actor_id": actor.id, "fields": sorted(changes)})
    row = await _user_admin_row(conn, user_id)
    return UserAdminResponse(**dict(row))
