from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ReportTable(BaseModel):
    code: str
    title: str
    columns: list[str]
    rows: list[dict]
    summary: dict = Field(default_factory=dict)


class ReportExportRequest(BaseModel):
    format: Literal["csv", "xlsx", "pdf"]
    filters: dict = Field(default_factory=dict)
    columns: list[str] | None = None


class ReportPresetCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    report_code: str = Field(pattern="^[a-z_]{2,50}$")
    filters: dict = Field(default_factory=dict)
    columns: list[str] | None = None


class ReportPresetItem(ReportPresetCreate):
    id: UUID
    created_at: datetime
    updated_at: datetime


class ReportScheduleCreate(BaseModel):
    report_code: str = Field(pattern="^[a-z_]{2,50}$")
    filters: dict = Field(default_factory=dict)
    recipients: list[str] = Field(min_length=1, max_length=100)
    cron: str = Field(min_length=5, max_length=120)
    format: Literal["csv", "xlsx", "pdf"] = "xlsx"
    enabled: bool = True

    @field_validator("recipients")
    @classmethod
    def validate_emails(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            email = value.strip().lower()
            if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
                raise ValueError(f"Некорректный e-mail: {value}")
            normalized.append(email)
        return normalized


class ReportScheduleItem(ReportScheduleCreate):
    id: UUID
    last_run_at: datetime | None
    next_run_at: datetime | None
    created_at: datetime


class ReportRunItem(BaseModel):
    id: UUID
    schedule_id: UUID | None
    report_code: str
    status: str
    recipients: list[str] | None
    storage_key: str | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None
