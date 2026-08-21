from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


ReportBasis = Literal["planned", "online", "active"]


class ProductivityRow(BaseModel):
    employee_id: UUID
    employee_name: str
    department_id: UUID | None
    department_name: str | None
    timezone: str
    planned_seconds: int
    online_seconds: int
    productive_seconds: int
    neutral_seconds: int
    unproductive_seconds: int
    idle_seconds: int
    locked_seconds: int
    break_seconds: int
    absence_seconds: int
    productive_percent: float
    unproductive_percent: float
    idle_percent: float
    previous_productive_percent: float
    delta_productive_pp: float
    grade: str
    grade_label: str


class ProductivityTotals(BaseModel):
    planned_seconds: int
    online_seconds: int
    productive_seconds: int
    neutral_seconds: int
    unproductive_seconds: int
    idle_seconds: int
    locked_seconds: int
    break_seconds: int
    absence_seconds: int
    productive_percent: float
    unproductive_percent: float
    idle_percent: float
    previous_productive_percent: float
    delta_productive_pp: float


class ProductivityReport(BaseModel):
    range_start: datetime
    range_end: datetime
    previous_range_start: datetime
    previous_range_end: datetime
    basis: ReportBasis
    rows: list[ProductivityRow]
    totals: ProductivityTotals


class DashboardKpis(BaseModel):
    online_now: int
    employees: int
    productivity_percent: float
    tracked_seconds: int
    low_productivity: int


class DepartmentBreakdown(BaseModel):
    department_id: UUID | None
    department_name: str
    employees: int
    productive_seconds: int
    neutral_seconds: int
    unproductive_seconds: int
    idle_seconds: int
    productivity_percent: float


class EmployeeScore(BaseModel):
    employee_id: UUID
    employee_name: str
    department_name: str | None
    productive_percent: float
    tracked_seconds: int
    grade: str


class TrendPoint(BaseModel):
    day: date
    productive_percent: float
    productive_seconds: int
    active_seconds: int


class DashboardResponse(BaseModel):
    range_start: datetime
    range_end: datetime
    kpis: DashboardKpis
    departments: list[DepartmentBreakdown]
    top_employees: list[EmployeeScore]
    bottom_employees: list[EmployeeScore]
    trend: list[TrendPoint]
    alerts: list[str]
