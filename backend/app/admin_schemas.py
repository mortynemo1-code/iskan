from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from .admin_validation import validate_category_code, validate_hex_color, validate_rule_pattern


Productivity = Literal["PRODUCTIVE", "NEUTRAL", "UNPRODUCTIVE"]
MatchField = Literal["process_name", "window_title", "url_domain", "url_full", "file_path"]
MatchType = Literal["exact", "contains", "wildcard", "regex"]


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parent_id: UUID | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()


class DepartmentResponse(BaseModel):
    id: UUID
    name: str
    parent_id: UUID | None
    employee_count: int
    created_at: datetime


class EmployeeCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    department_id: UUID | None = None
    position_title: str | None = Field(default=None, max_length=160)
    hire_date: date | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=80)
    planned_daily_minutes: int = Field(default=480, ge=0, le=1440)

    @field_validator("full_name", "timezone")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        return value.strip().lower() or None if value is not None else None


class EmployeePatch(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, max_length=320)
    department_id: UUID | None = None
    position_title: str | None = Field(default=None, max_length=160)
    hire_date: date | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=80)
    status: Literal["active", "inactive"] | None = None
    planned_daily_minutes: int | None = Field(default=None, ge=0, le=1440)

    @model_validator(mode="after")
    def require_change(self) -> "EmployeePatch":
        if not self.model_fields_set:
            raise ValueError("Нужно передать хотя бы одно изменение")
        return self


class EmployeeResponse(BaseModel):
    id: UUID
    full_name: str
    email: str | None
    department_id: UUID | None
    department_name: str | None
    position_title: str | None
    hire_date: date | None
    timezone: str
    planned_daily_minutes: int
    status: str
    devices_count: int
    created_at: datetime


class DeviceAdminPatch(BaseModel):
    employee_id: UUID | None = None
    is_approved: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "DeviceAdminPatch":
        if not self.model_fields_set:
            raise ValueError("Нужно передать хотя бы одно изменение")
        return self


class DeviceAdminResponse(BaseModel):
    id: UUID
    employee_id: UUID | None
    employee_name: str | None
    hostname: str
    os_version: str
    agent_version: str
    is_approved: bool
    last_seen: datetime | None
    last_activity_state: str | None
    created_at: datetime


class DeviceCommandRequest(BaseModel):
    command: Literal["restart_agent", "send_logs", "update_agent"]


class WindowsAccountPatch(BaseModel):
    employee_id: UUID


class WindowsAccountResponse(BaseModel):
    id: UUID
    device_id: UUID
    hostname: str
    sid: str
    username: str
    employee_id: UUID | None
    employee_name: str | None
    quarantined_events: int
    created_at: datetime


class UpdateReleasePatch(BaseModel):
    rollout_percent: int | None = Field(default=None, ge=0, le=100)
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "UpdateReleasePatch":
        if not self.model_fields_set:
            raise ValueError("Нужно передать хотя бы одно изменение")
        return self


class CategoryCreate(BaseModel):
    code: str
    name: str = Field(min_length=1, max_length=120)
    productivity: Productivity
    color: str = "#78909C"

    _normalize_code = field_validator("code")(validate_category_code)
    _normalize_color = field_validator("color")(validate_hex_color)


class CategoryPatch(BaseModel):
    code: str | None = None
    name: str | None = Field(default=None, min_length=1, max_length=120)
    productivity: Productivity | None = None
    color: str | None = None

    _normalize_code = field_validator("code")(validate_category_code)
    _normalize_color = field_validator("color")(validate_hex_color)

    @model_validator(mode="after")
    def require_change(self) -> "CategoryPatch":
        if not self.model_fields_set:
            raise ValueError("Нужно передать хотя бы одно изменение")
        return self


class CategoryResponse(BaseModel):
    id: int
    code: str
    name: str
    productivity: Productivity
    color: str
    is_system: bool
    rules_count: int
    created_at: datetime


class RuleCreate(BaseModel):
    priority: int = Field(ge=0, le=100_000)
    match_field: MatchField
    match_type: MatchType
    pattern: str = Field(min_length=1, max_length=500)
    category_id: int = Field(gt=0)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_pattern(self) -> "RuleCreate":
        self.pattern = validate_rule_pattern(self.match_type, self.pattern)
        return self


class RulePatch(BaseModel):
    priority: int | None = Field(default=None, ge=0, le=100_000)
    match_field: MatchField | None = None
    match_type: MatchType | None = None
    pattern: str | None = Field(default=None, min_length=1, max_length=500)
    category_id: int | None = Field(default=None, gt=0)
    enabled: bool | None = None

    @model_validator(mode="after")
    def require_change(self) -> "RulePatch":
        if not self.model_fields_set:
            raise ValueError("Нужно передать хотя бы одно изменение")
        if self.match_type is not None and self.pattern is not None:
            self.pattern = validate_rule_pattern(self.match_type, self.pattern)
        return self


class RuleResponse(BaseModel):
    id: int
    priority: int
    match_field: MatchField
    match_type: MatchType
    pattern: str
    category_id: int
    category_name: str
    productivity: Productivity
    enabled: bool
    created_at: datetime


class RuleTestRequest(BaseModel):
    match_field: MatchField
    match_type: MatchType
    pattern: str = Field(min_length=1, max_length=500)
    days: int = Field(default=7, ge=1, le=90)

    @model_validator(mode="after")
    def validate_pattern(self) -> "RuleTestRequest":
        self.pattern = validate_rule_pattern(self.match_type, self.pattern)
        return self
