from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


RoleCode = Literal["superadmin", "admin", "hr", "manager", "observer", "employee"]
ScopeType = Literal["organization", "department", "employee"]


class LoginRequest(BaseModel):
    login: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=1000)
    totp_code: str | None = Field(default=None, pattern=r"^\d{6}$")

    @field_validator("login")
    @classmethod
    def normalize_login(cls, value: str) -> str:
        return value.strip().lower()


class TotpConfirmRequest(BaseModel):
    setup_token: str
    code: str = Field(pattern=r"^\d{6}$")


class UserInfo(BaseModel):
    id: UUID
    login: str
    display_name: str
    role: str
    employee_id: UUID | None
    scope_type: str
    permissions: list[str]


class AuthResponse(BaseModel):
    status: Literal["AUTHENTICATED", "TOTP_REQUIRED", "TOTP_SETUP_REQUIRED"]
    access_token: str | None = None
    expires_in: int | None = None
    user: UserInfo | None = None
    setup_token: str | None = None
    totp_secret: str | None = None
    totp_uri: str | None = None


class RefreshResponse(BaseModel):
    access_token: str
    expires_in: int
    user: UserInfo


class RoleResponse(BaseModel):
    code: str
    name: str
    permissions: list[str]


class RolePermissionsPatch(BaseModel):
    permissions: list[str] = Field(max_length=200)


class UserAdminCreate(BaseModel):
    login: str = Field(min_length=2, max_length=200)
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=1000)
    role_code: RoleCode
    employee_id: UUID | None = None
    scope_type: ScopeType = "organization"
    department_ids: list[UUID] = Field(default_factory=list, max_length=100)
    employee_ids: list[UUID] = Field(default_factory=list, max_length=500)

    @field_validator("login")
    @classmethod
    def normalize_login(cls, value: str) -> str:
        return value.strip().lower()

    @model_validator(mode="after")
    def validate_scope(self) -> "UserAdminCreate":
        if self.role_code == "employee" and self.employee_id is None:
            raise ValueError("Для роли employee нужно выбрать сотрудника")
        if self.scope_type == "department" and not self.department_ids:
            raise ValueError("Для скоупа отдела выберите хотя бы один отдел")
        return self


class UserAdminPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    password: str | None = Field(default=None, min_length=12, max_length=1000)
    role_code: RoleCode | None = None
    employee_id: UUID | None = None
    scope_type: ScopeType | None = None
    department_ids: list[UUID] | None = Field(default=None, max_length=100)
    employee_ids: list[UUID] | None = Field(default=None, max_length=500)
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "UserAdminPatch":
        if not self.model_fields_set:
            raise ValueError("Нужно передать хотя бы одно изменение")
        return self


class UserAdminResponse(BaseModel):
    id: UUID
    login: str
    display_name: str
    role_code: str
    role_name: str
    employee_id: UUID | None
    employee_name: str | None
    scope_type: str
    is_active: bool
    totp_enabled: bool
    department_ids: list[UUID]
    employee_ids: list[UUID]
