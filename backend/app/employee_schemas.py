from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel

from .analytics_schemas import ProductivityRow, TrendPoint


class ApplicationUsage(BaseModel):
    key: str
    label: str
    kind: str
    category_id: int | None
    category_name: str | None
    productivity: str
    seconds: int
    percent: float


class EmployeeDevice(BaseModel):
    id: UUID
    hostname: str
    os_version: str
    agent_version: str
    is_approved: bool
    last_seen: datetime | None
    last_activity_state: str | None


class EmployeeAbsenceSummary(BaseModel):
    approved_days: int
    pending_requests: int
    violations: int
    late_minutes: int


class RecentActivity(BaseModel):
    event_uuid: UUID
    ts_start: datetime
    ts_end: datetime
    duration_sec: int
    state: str
    app_name: str | None
    process_name: str | None
    window_title: str | None
    url_domain: str | None
    url_path: str | None
    category_id: int | None
    category_name: str | None
    screenshot_id: int | None


class EmployeeOverview(BaseModel):
    id: UUID
    full_name: str
    email: str | None
    department_id: UUID | None
    department_name: str | None
    position_title: str | None
    hire_date: date | None
    timezone: str
    status: str
    planned_daily_minutes: int
    metrics: ProductivityRow
    trend: list[TrendPoint]
    applications: list[ApplicationUsage]
    devices: list[EmployeeDevice]
    absence_summary: EmployeeAbsenceSummary
    recent_activity: list[RecentActivity]
