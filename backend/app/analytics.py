import csv
import io
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from .analytics_calculations import performance_grade, percentage, planned_seconds, report_denominator
from .analytics_schemas import (
    DashboardKpis,
    DashboardResponse,
    DepartmentBreakdown,
    EmployeeScore,
    ProductivityReport,
    ProductivityRow,
    ProductivityTotals,
    ReportBasis,
    TrendPoint,
)
from .auth import CurrentUser, require_permission, visible_employee_ids
from .config import Settings, get_settings
from .database import connection


router = APIRouter(prefix="/api/v1", tags=["analytics"])


async def db() -> asyncpg.Connection:
    async with connection() as conn:
        yield conn


def validate_range(range_start: datetime, range_end: datetime) -> None:
    if range_start.tzinfo is None or range_end.tzinfo is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Период должен включать часовой пояс")
    if range_end <= range_start:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Конец периода должен быть позже начала")
    if range_end - range_start > timedelta(days=366):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Период ограничен 366 днями")


async def fetch_employee_aggregates(
    conn: asyncpg.Connection,
    range_start: datetime,
    range_end: datetime,
    visible_ids: set[UUID] | None,
    department_id: UUID | None,
    employee_id: UUID | None,
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT e.id AS employee_id, e.full_name AS employee_name,
               e.department_id, COALESCE(d.name, e.department_name) AS department_name,
               e.timezone, e.planned_daily_minutes,
               COALESCE(sum(EXTRACT(EPOCH FROM (LEAST(a.ts_end, $2) - GREATEST(a.ts_start, $1))))
                   FILTER (WHERE a.id IS NOT NULL), 0)::bigint AS online_seconds,
               COALESCE(sum(EXTRACT(EPOCH FROM (LEAST(a.ts_end, $2) - GREATEST(a.ts_start, $1))))
                   FILTER (WHERE a.state='PRODUCTIVE'), 0)::bigint AS productive_seconds,
               COALESCE(sum(EXTRACT(EPOCH FROM (LEAST(a.ts_end, $2) - GREATEST(a.ts_start, $1))))
                   FILTER (WHERE a.state='NEUTRAL'), 0)::bigint AS neutral_seconds,
               COALESCE(sum(EXTRACT(EPOCH FROM (LEAST(a.ts_end, $2) - GREATEST(a.ts_start, $1))))
                   FILTER (WHERE a.state='UNPRODUCTIVE'), 0)::bigint AS unproductive_seconds,
               COALESCE(sum(EXTRACT(EPOCH FROM (LEAST(a.ts_end, $2) - GREATEST(a.ts_start, $1))))
                   FILTER (WHERE a.state='IDLE'), 0)::bigint AS idle_seconds,
               COALESCE(sum(EXTRACT(EPOCH FROM (LEAST(a.ts_end, $2) - GREATEST(a.ts_start, $1))))
                   FILTER (WHERE a.state='LOCKED'), 0)::bigint AS locked_seconds,
               COALESCE(sum(EXTRACT(EPOCH FROM (LEAST(a.ts_end, $2) - GREATEST(a.ts_start, $1))))
                   FILTER (WHERE a.state='BREAK'), 0)::bigint AS break_seconds
        FROM employees e
        LEFT JOIN departments d ON d.id=e.department_id
        LEFT JOIN activity_events a ON a.employee_id=e.id AND a.ts_start<$2 AND a.ts_end>$1
        WHERE e.status='active'
          AND ($3::uuid[] IS NULL OR e.id=ANY($3::uuid[]))
          AND ($4::uuid IS NULL OR e.department_id=$4)
          AND ($5::uuid IS NULL OR e.id=$5)
        GROUP BY e.id, d.name
        ORDER BY e.full_name
        """,
        range_start,
        range_end,
        None if visible_ids is None else list(visible_ids),
        department_id,
        employee_id,
    )


def row_values(row: asyncpg.Record, range_start: datetime, range_end: datetime) -> dict[str, int]:
    return {
        "planned_seconds": planned_seconds(
            range_start,
            range_end,
            row["timezone"],
            row["planned_daily_minutes"],
        ),
        "online_seconds": int(row["online_seconds"]),
        "productive_seconds": int(row["productive_seconds"]),
        "neutral_seconds": int(row["neutral_seconds"]),
        "unproductive_seconds": int(row["unproductive_seconds"]),
        "idle_seconds": int(row["idle_seconds"]),
        "locked_seconds": int(row["locked_seconds"]),
        "break_seconds": int(row["break_seconds"]),
        "absence_seconds": 0,
    }


async def build_productivity_report(
    conn: asyncpg.Connection,
    user: CurrentUser,
    range_start: datetime,
    range_end: datetime,
    basis: ReportBasis,
    department_id: UUID | None,
    employee_id: UUID | None,
    sort: str,
    direction: str,
) -> ProductivityReport:
    validate_range(range_start, range_end)
    visible_ids = await visible_employee_ids(conn, user)
    previous_end = range_start
    previous_start = range_start - (range_end - range_start)
    current_rows = await fetch_employee_aggregates(
        conn, range_start, range_end, visible_ids, department_id, employee_id
    )
    previous_rows = await fetch_employee_aggregates(
        conn, previous_start, previous_end, visible_ids, department_id, employee_id
    )
    previous_by_employee = {row["employee_id"]: row for row in previous_rows}
    report_rows: list[ProductivityRow] = []
    previous_total_productive = 0
    previous_total_denominator = 0
    total_values = {
        key: 0
        for key in (
            "planned_seconds", "online_seconds", "productive_seconds", "neutral_seconds",
            "unproductive_seconds", "idle_seconds", "locked_seconds", "break_seconds", "absence_seconds",
        )
    }
    for row in current_rows:
        values = row_values(row, range_start, range_end)
        denominator = report_denominator(basis, values)
        productive_percent = percentage(values["productive_seconds"], denominator)
        previous = previous_by_employee.get(row["employee_id"])
        previous_values = row_values(previous, previous_start, previous_end) if previous else {
            **{key: 0 for key in values},
            "planned_seconds": planned_seconds(previous_start, previous_end, row["timezone"], row["planned_daily_minutes"]),
        }
        previous_denominator = report_denominator(basis, previous_values)
        previous_percent = percentage(previous_values["productive_seconds"], previous_denominator)
        previous_total_productive += previous_values["productive_seconds"]
        previous_total_denominator += previous_denominator
        grade, grade_label = performance_grade(productive_percent)
        report_rows.append(
            ProductivityRow(
                employee_id=row["employee_id"],
                employee_name=row["employee_name"],
                department_id=row["department_id"],
                department_name=row["department_name"],
                timezone=row["timezone"],
                **values,
                productive_percent=productive_percent,
                unproductive_percent=percentage(values["unproductive_seconds"], denominator),
                idle_percent=percentage(values["idle_seconds"], denominator),
                previous_productive_percent=previous_percent,
                delta_productive_pp=round(productive_percent - previous_percent, 1),
                grade=grade,
                grade_label=grade_label,
            )
        )
        for key in total_values:
            total_values[key] += values[key]

    sort_fields = {
        "employee": lambda item: item.employee_name.lower(),
        "department": lambda item: (item.department_name or "").lower(),
        "productive": lambda item: item.productive_percent,
        "unproductive": lambda item: item.unproductive_percent,
        "idle": lambda item: item.idle_percent,
        "online": lambda item: item.online_seconds,
    }
    report_rows.sort(key=sort_fields.get(sort, sort_fields["employee"]), reverse=direction == "desc")
    total_denominator = report_denominator(basis, total_values)
    total_productive_percent = percentage(total_values["productive_seconds"], total_denominator)
    previous_total_percent = percentage(previous_total_productive, previous_total_denominator)
    totals = ProductivityTotals(
        **total_values,
        productive_percent=total_productive_percent,
        unproductive_percent=percentage(total_values["unproductive_seconds"], total_denominator),
        idle_percent=percentage(total_values["idle_seconds"], total_denominator),
        previous_productive_percent=previous_total_percent,
        delta_productive_pp=round(total_productive_percent - previous_total_percent, 1),
    )
    return ProductivityReport(
        range_start=range_start,
        range_end=range_end,
        previous_range_start=previous_start,
        previous_range_end=previous_end,
        basis=basis,
        rows=report_rows,
        totals=totals,
    )


@router.get("/reports/productivity", response_model=ProductivityReport)
async def productivity_report(
    range_start: datetime = Query(alias="from"),
    range_end: datetime = Query(alias="to"),
    basis: ReportBasis = "planned",
    department_id: UUID | None = None,
    employee_id: UUID | None = None,
    sort: str = Query(default="employee", pattern="^(employee|department|productive|unproductive|idle|online)$"),
    direction: str = Query(default="asc", pattern="^(asc|desc)$"),
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("reports:view")),
) -> ProductivityReport:
    return await build_productivity_report(
        conn, user, range_start, range_end, basis, department_id, employee_id, sort, direction
    )


@router.get("/reports/productivity.csv")
async def productivity_report_csv(
    range_start: datetime = Query(alias="from"),
    range_end: datetime = Query(alias="to"),
    basis: ReportBasis = "planned",
    department_id: UUID | None = None,
    employee_id: UUID | None = None,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("reports:view")),
) -> Response:
    report = await build_productivity_report(
        conn, user, range_start, range_end, basis, department_id, employee_id, "employee", "asc"
    )
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Сотрудник", "Отдел", "План, ч", "Онлайн, ч", "Работа, ч", "Нейтрально, ч",
        "Непродуктивно, ч", "Простой, ч", "% работы", "% непродуктивного", "% простоя", "Оценка",
    ])
    for row in report.rows:
        writer.writerow([
            row.employee_name, row.department_name or "", round(row.planned_seconds / 3600, 2),
            round(row.online_seconds / 3600, 2), round(row.productive_seconds / 3600, 2),
            round(row.neutral_seconds / 3600, 2), round(row.unproductive_seconds / 3600, 2),
            round(row.idle_seconds / 3600, 2), row.productive_percent, row.unproductive_percent,
            row.idle_percent, row.grade_label,
        ])
    return Response(
        content="\ufeff" + output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="productivity.csv"'},
    )


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    range_start: datetime = Query(alias="from"),
    range_end: datetime = Query(alias="to"),
    department_id: UUID | None = None,
    conn: asyncpg.Connection = Depends(db),
    user: CurrentUser = Depends(require_permission("reports:view")),
    settings: Settings = Depends(get_settings),
) -> DashboardResponse:
    report = await build_productivity_report(
        conn, user, range_start, range_end, "active", department_id, None, "productive", "desc"
    )
    visible_ids = await visible_employee_ids(conn, user)
    online_now = await conn.fetchval(
        """
        SELECT count(DISTINCT e.id)::int
        FROM employees e JOIN devices d ON d.employee_id=e.id
        WHERE d.is_approved=true AND d.last_seen >= now() - ($1 * interval '1 second')
          AND ($2::uuid[] IS NULL OR e.id=ANY($2::uuid[]))
          AND ($3::uuid IS NULL OR e.department_id=$3)
        """,
        settings.presence_ttl_seconds,
        None if visible_ids is None else list(visible_ids),
        department_id,
    )
    departments: dict[tuple[UUID | None, str], dict[str, int]] = {}
    for row in report.rows:
        key = (row.department_id, row.department_name or "Без отдела")
        item = departments.setdefault(
            key,
            {"employees": 0, "productive_seconds": 0, "neutral_seconds": 0, "unproductive_seconds": 0, "idle_seconds": 0},
        )
        item["employees"] += 1
        for field in ("productive_seconds", "neutral_seconds", "unproductive_seconds", "idle_seconds"):
            item[field] += getattr(row, field)
    department_items = []
    for (item_id, name), values in departments.items():
        active = values["productive_seconds"] + values["neutral_seconds"] + values["unproductive_seconds"]
        department_items.append(
            DepartmentBreakdown(
                department_id=item_id,
                department_name=name,
                **values,
                productivity_percent=percentage(values["productive_seconds"], active),
            )
        )
    department_items.sort(key=lambda item: item.productivity_percent, reverse=True)
    score_items = [
        EmployeeScore(
            employee_id=row.employee_id,
            employee_name=row.employee_name,
            department_name=row.department_name,
            productive_percent=row.productive_percent,
            tracked_seconds=row.online_seconds,
            grade=row.grade,
        )
        for row in report.rows if row.online_seconds > 0
    ]
    score_items.sort(key=lambda item: item.productive_percent, reverse=True)
    trend_rows = await conn.fetch(
        """
        SELECT (a.ts_start AT TIME ZONE 'UTC')::date AS day,
               COALESCE(sum(a.duration_sec) FILTER (WHERE a.state='PRODUCTIVE'), 0)::bigint AS productive_seconds,
               COALESCE(sum(a.duration_sec) FILTER (WHERE a.state IN ('PRODUCTIVE','NEUTRAL','UNPRODUCTIVE')), 0)::bigint AS active_seconds
        FROM activity_events a JOIN employees e ON e.id=a.employee_id
        WHERE a.ts_start<$2 AND a.ts_end>$1
          AND ($3::uuid[] IS NULL OR e.id=ANY($3::uuid[]))
          AND ($4::uuid IS NULL OR e.department_id=$4)
        GROUP BY day ORDER BY day
        """,
        range_start,
        range_end,
        None if visible_ids is None else list(visible_ids),
        department_id,
    )
    trend = [
        TrendPoint(
            day=row["day"],
            productive_percent=percentage(int(row["productive_seconds"]), int(row["active_seconds"])),
            productive_seconds=int(row["productive_seconds"]),
            active_seconds=int(row["active_seconds"]),
        )
        for row in trend_rows
    ]
    low_productivity = sum(1 for row in score_items if row.productive_percent < 50)
    no_activity = sum(1 for row in report.rows if row.online_seconds == 0)
    alerts = []
    if low_productivity:
        alerts.append(f"У {low_productivity} сотрудников продуктивность ниже 50%")
    if no_activity:
        alerts.append(f"Нет активности у {no_activity} сотрудников за выбранный период")
    return DashboardResponse(
        range_start=range_start,
        range_end=range_end,
        kpis=DashboardKpis(
            online_now=online_now or 0,
            employees=len(report.rows),
            productivity_percent=report.totals.productive_percent,
            tracked_seconds=report.totals.online_seconds,
            low_productivity=low_productivity,
        ),
        departments=department_items,
        top_employees=score_items[:5],
        bottom_employees=list(reversed(score_items[-5:])),
        trend=trend,
        alerts=alerts,
    )
