from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


Effect = Literal["excludes_day", "counts_as_violation", "adds_plan_time", "neutral"]
AbsenceStatus = Literal["draft", "pending", "approved", "rejected"]
ScheduleKind = Literal["fixed", "shift", "flexible", "individual"]


class AbsenceTypeBase(BaseModel):
    code: str = Field(pattern="^[A-Z][A-Z0-9_]{1,49}$")
    name: str = Field(min_length=1, max_length=120)
    color: str = Field(pattern="^#[0-9A-Fa-f]{6}$")
    effect: Effect = "neutral"
    requires_document: bool = False

    @field_validator("code")
    @classmethod
    def uppercase_code(cls, value: str) -> str:
        return value.upper()


class AbsenceTypeCreate(AbsenceTypeBase):
    pass


class AbsenceTypePatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    color: str | None = Field(default=None, pattern="^#[0-9A-Fa-f]{6}$")
    effect: Effect | None = None
    requires_document: bool | None = None


class AbsenceTypeItem(AbsenceTypeBase):
    id: int
    is_system: bool


class AbsenceCreate(BaseModel):
    employee_ids: list[UUID] = Field(min_length=1, max_length=500)
    type_id: int = Field(gt=0)
    date_from: date
    date_to: date
    minutes: int | None = Field(default=None, ge=1, le=1440)
    reason: str | None = Field(default=None, max_length=1000)
    comment: str | None = Field(default=None, max_length=3000)
    severity: int | None = Field(default=None, ge=1, le=5)
    status: AbsenceStatus = "pending"

    @model_validator(mode="after")
    def validate_dates(self) -> "AbsenceCreate":
        if self.date_to < self.date_from:
            raise ValueError("date_to должна быть не раньше date_from")
        return self


class AbsencePatch(BaseModel):
    type_id: int | None = Field(default=None, gt=0)
    date_from: date | None = None
    date_to: date | None = None
    minutes: int | None = Field(default=None, ge=1, le=1440)
    reason: str | None = Field(default=None, max_length=1000)
    comment: str | None = Field(default=None, max_length=3000)
    severity: int | None = Field(default=None, ge=1, le=5)


class AbsenceDecision(BaseModel):
    comment: str | None = Field(default=None, max_length=3000)


class AbsenceItem(BaseModel):
    id: UUID
    employee_id: UUID
    employee_name: str
    department_name: str | None
    type_id: int
    type_code: str
    type_name: str
    color: str
    effect: str
    requires_document: bool
    date_from: date
    date_to: date
    minutes: int | None
    reason: str | None
    comment: str | None
    attachment_key: str | None
    severity: int | None
    status: str
    is_auto: bool
    created_by: UUID | None
    approved_by: UUID | None
    approved_at: datetime | None
    created_at: datetime


class CalendarEmployee(BaseModel):
    employee_id: UUID
    full_name: str
    department_name: str | None
    events: list[AbsenceItem]


class AbsenceCalendar(BaseModel):
    month: str
    days: int
    employees: list[CalendarEmployee]


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: ScheduleKind
    rules: dict


class ScheduleItem(BaseModel):
    id: UUID
    name: str
    kind: str
    rules: dict
    assignments_count: int = 0


class ScheduleAssignmentCreate(BaseModel):
    employee_ids: list[UUID] = Field(min_length=1, max_length=500)
    schedule_id: UUID
    valid_from: date
    valid_to: date | None = None

    @model_validator(mode="after")
    def validate_dates(self) -> "ScheduleAssignmentCreate":
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to должна быть не раньше valid_from")
        return self


class ScheduleAssignmentItem(BaseModel):
    id: UUID
    employee_id: UUID
    employee_name: str
    schedule_id: UUID
    schedule_name: str
    valid_from: date
    valid_to: date | None


class HolidayItem(BaseModel):
    holiday_date: date
    name: str = Field(min_length=1, max_length=160)
    kind: Literal["holiday", "working", "shortened"] = "holiday"
