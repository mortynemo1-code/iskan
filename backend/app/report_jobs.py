import asyncio
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import PurePosixPath
from uuid import uuid4

from .auth import load_current_user
from .config import get_settings
from .database import connection
from .reports import export_csv, export_pdf, export_xlsx, table_from_export
from .storage import ObjectStorage


def cron_field_matches(field: str, value: int) -> bool:
    if field == "*": return True
    for part in field.split(","):
        if "/" in part:
            base, step_text = part.split("/", 1)
            try: step = int(step_text)
            except ValueError: continue
            if step > 0 and (base == "*" or int(base) <= value) and value % step == 0: return True
        elif "-" in part:
            try: start, end = map(int, part.split("-", 1))
            except ValueError: continue
            if start <= value <= end: return True
        else:
            try:
                if int(part) == value: return True
            except ValueError: continue
    return False


def cron_matches(expression: str, instant: datetime) -> bool:
    fields = expression.split()
    if len(fields) != 5: return False
    minute, hour, day, month, weekday = fields
    cron_weekday = (instant.weekday() + 1) % 7
    return all((cron_field_matches(field, value) for field, value in (
        (minute, instant.minute), (hour, instant.hour), (day, instant.day), (month, instant.month), (weekday, cron_weekday),
    )))


def next_cron_after(expression: str, instant: datetime) -> datetime:
    candidate = instant.astimezone(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(60 * 24 * 370):
        if cron_matches(expression, candidate): return candidate
        candidate += timedelta(minutes=1)
    raise ValueError("Расписание не имеет запуска в ближайший год")


def send_email(subject: str, summary: str, recipients: list[str], filename: str, content: bytes, media_type: str) -> None:
    settings = get_settings()
    if not settings.smtp_host: raise RuntimeError("SMTP_HOST не настроен")
    message = EmailMessage(); message["Subject"] = subject; message["From"] = settings.smtp_from; message["To"] = ", ".join(recipients)
    message.set_content(summary)
    maintype, subtype = media_type.split("/", 1); message.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls: smtp.starttls()
        if settings.smtp_username: smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(message)


async def process_report_schedules() -> int:
    processed = 0
    async with connection() as conn:
        schedules = await conn.fetch(
            """SELECT * FROM report_schedules WHERE enabled=true AND COALESCE(next_run_at,now())<=now()
               ORDER BY next_run_at NULLS FIRST LIMIT 10 FOR UPDATE SKIP LOCKED"""
        )
        for schedule in schedules:
            run_id = await conn.fetchval(
                """INSERT INTO report_runs(schedule_id,report_code,status,recipients)
                   VALUES($1,$2,'running',$3) RETURNING id""", schedule["id"], schedule["report_code"], schedule["recipients"],
            )
            try:
                user = await load_current_user(conn, schedule["user_id"])
                if user is None: raise RuntimeError("Владелец расписания отключён")
                table = await table_from_export(conn, user, schedule["report_code"], schedule["filters_json"])
                if schedule["format"] == "csv": content, media = export_csv(table, table.columns), "text/csv"
                elif schedule["format"] == "pdf": content, media = export_pdf(table, table.columns), "application/pdf"
                else: content, media = export_xlsx(table, table.columns), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                filename = f"{schedule['report_code']}.{schedule['format']}"
                storage_key = str(PurePosixPath("scheduled-reports", str(datetime.now(UTC).year), f"{uuid4().hex}-{filename}"))
                await ObjectStorage().put_bytes(storage_key, content, media)
                summary = f"{table.title}\nСтрок в отчёте: {len(table.rows)}\nСформировано: {datetime.now(UTC).isoformat()}"
                await asyncio.to_thread(send_email, table.title, summary, list(schedule["recipients"]), filename, content, media)
                await conn.execute("UPDATE report_runs SET status='sent',storage_key=$2,finished_at=now() WHERE id=$1", run_id, storage_key)
                processed += 1
            except Exception as error:
                await conn.execute("UPDATE report_runs SET status='failed',error=$2,finished_at=now() WHERE id=$1", run_id, str(error)[:3000])
            try: next_run = next_cron_after(schedule["cron"], datetime.now(UTC))
            except ValueError: next_run = datetime.now(UTC) + timedelta(days=1)
            await conn.execute("UPDATE report_schedules SET last_run_at=now(),next_run_at=$2 WHERE id=$1", schedule["id"], next_run)
    return processed


async def report_schedule_worker() -> None:
    while True:
        try: await process_report_schedules()
        except asyncio.CancelledError: raise
        except Exception: pass
        await asyncio.sleep(30)
