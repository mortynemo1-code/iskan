import { FormEvent, useCallback, useEffect, useState } from "react";

type Schedule = { id: string; name: string; kind: string; rules: Record<string, unknown>; assignments_count: number };
type Assignment = { id: string; employee_id: string; employee_name: string; schedule_id: string; schedule_name: string; valid_from: string; valid_to: string | null };
type Employee = { id: string; full_name: string };
type AbsenceType = { id: number; code: string; name: string; color: string; effect: string; requires_document: boolean; is_system: boolean };
type Holiday = { holiday_date: string; name: string; kind: string };

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, headers: init?.body ? { "Content-Type": "application/json", ...init.headers } : init?.headers });
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail ?? `HTTP ${response.status}`); }
  return response.status === 204 ? undefined as T : response.json();
}

export function ScheduleAdmin() {
  const [schedules, setSchedules] = useState<Schedule[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [types, setTypes] = useState<AbsenceType[]>([]);
  const [holidays, setHolidays] = useState<Holiday[]>([]);
  const [year, setYear] = useState(new Date().getFullYear());
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [scheduleRows, assignmentRows, employeeRows, typeRows, holidayRows] = await Promise.all([
        request<Schedule[]>("/api/v1/schedules"), request<Assignment[]>("/api/v1/schedule-assignments"),
        request<Employee[]>("/api/v1/admin/employees"), request<AbsenceType[]>("/api/v1/absence-types"),
        request<Holiday[]>(`/api/v1/holidays?year=${year}`),
      ]);
      setSchedules(scheduleRows); setAssignments(assignmentRows); setEmployees(employeeRows); setTypes(typeRows); setHolidays(holidayRows); setError(null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Ошибка загрузки"); }
  }, [year]);

  useEffect(() => { void load(); }, [load]);
  const mutate = async (operation: () => Promise<unknown>, success: string) => { try { setError(null); await operation(); setMessage(success); await load(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Операция не выполнена"); } };

  const createSchedule = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form);
    void mutate(() => request("/api/v1/schedules", { method: "POST", body: JSON.stringify({ name: values.get("name"), kind: "fixed", rules: {
      weekdays: values.getAll("weekday").map(Number), start: values.get("start"), end: values.get("end"), break_minutes: Number(values.get("break_minutes")), late_tolerance_minutes: Number(values.get("tolerance")),
    } }) }), "График создан").then(() => form.reset());
  };

  const assign = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form);
    void mutate(() => request("/api/v1/schedule-assignments", { method: "POST", body: JSON.stringify({ employee_ids: [values.get("employee_id")], schedule_id: values.get("schedule_id"), valid_from: values.get("valid_from"), valid_to: values.get("valid_to") || null }) }), "График назначен").then(() => form.reset());
  };

  const createType = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form);
    void mutate(() => request("/api/v1/absence-types", { method: "POST", body: JSON.stringify({ code: values.get("code"), name: values.get("name"), color: values.get("color"), effect: values.get("effect"), requires_document: values.get("requires_document") === "on" }) }), "Тип события добавлен").then(() => form.reset());
  };

  const saveHoliday = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const values = new FormData(form); const day = String(values.get("holiday_date"));
    void mutate(() => request(`/api/v1/holidays/${day}`, { method: "PUT", body: JSON.stringify({ holiday_date: day, name: values.get("name"), kind: values.get("kind") }) }), "Производственный календарь обновлён").then(() => form.reset());
  };

  return <section className="admin-section schedule-admin">
    <div className="section-heading compact"><div><p className="eyebrow">Рабочее время</p><h2>Графики и кадровые справочники</h2></div></div>
    {(error || message) && <div className={`notice ${error ? "notice-error" : "notice-success"}`}>{error ?? message}</div>}
    <div className="schedule-admin-grid">
      <article className="admin-card"><div className="card-heading"><span>Графики работы</span><small>{schedules.length}</small></div>
        <form className="compact-admin-form" onSubmit={createSchedule}><input name="name" required placeholder="Например, Офис 5/2" /><div className="weekday-checks">{[1,2,3,4,5,6,7].map((day) => <label key={day}><input type="checkbox" name="weekday" value={day} defaultChecked={day <= 5} />{["Пн","Вт","Ср","Чт","Пт","Сб","Вс"][day - 1]}</label>)}</div><label><span>Начало</span><input name="start" type="time" defaultValue="09:00" required /></label><label><span>Конец</span><input name="end" type="time" defaultValue="18:00" required /></label><label><span>Перерыв, мин</span><input name="break_minutes" type="number" defaultValue="60" min="0" /></label><label><span>Допуск, мин</span><input name="tolerance" type="number" defaultValue="5" min="0" /></label><button className="primary-button">Добавить график</button></form>
        <div className="simple-list">{schedules.map((schedule) => <div key={schedule.id}><span><strong>{schedule.name}</strong><small>{schedule.kind} · назначений {schedule.assignments_count}</small></span><code>{String(schedule.rules.start ?? "—")}–{String(schedule.rules.end ?? "—")}</code></div>)}</div>
      </article>
      <article className="admin-card"><div className="card-heading"><span>Назначения</span><small>с историей</small></div>
        <form className="compact-admin-form assign-form" onSubmit={assign}><select name="employee_id" required defaultValue=""><option value="">Сотрудник</option>{employees.map((employee) => <option value={employee.id} key={employee.id}>{employee.full_name}</option>)}</select><select name="schedule_id" required defaultValue=""><option value="">График</option>{schedules.map((schedule) => <option value={schedule.id} key={schedule.id}>{schedule.name}</option>)}</select><label><span>Действует с</span><input name="valid_from" type="date" required /></label><label><span>По дату</span><input name="valid_to" type="date" /></label><button className="primary-button">Назначить</button></form>
        <div className="simple-list scroll-list">{assignments.map((item) => <div key={item.id}><span><strong>{item.employee_name}</strong><small>{item.schedule_name}</small></span><code>{item.valid_from}{item.valid_to ? ` — ${item.valid_to}` : " →"}</code></div>)}</div>
      </article>
      <article className="admin-card"><div className="card-heading"><span>Типы событий</span><small>{types.length}</small></div>
        <form className="compact-admin-form type-form" onSubmit={createType}><input name="code" required pattern="[A-Z][A-Z0-9_]+" placeholder="CUSTOM_EVENT" /><input name="name" required placeholder="Название" /><input name="color" type="color" defaultValue="#7E57C2" /><select name="effect" defaultValue="neutral"><option value="neutral">Нейтрально</option><option value="excludes_day">Исключает день</option><option value="counts_as_violation">Нарушение</option><option value="adds_plan_time">Добавляет план</option></select><label className="checkbox-field"><input name="requires_document" type="checkbox" /> Нужен документ</label><button className="primary-button">Добавить</button></form>
        <div className="type-chip-list">{types.map((item) => <span key={item.id} style={{ borderColor: item.color }}><i style={{ background: item.color }} />{item.name}<small>{item.effect}</small></span>)}</div>
      </article>
      <article className="admin-card"><div className="card-heading"><span>Производственный календарь</span><select value={year} onChange={(event) => setYear(Number(event.target.value))}>{[year-1,year,year+1].map((value) => <option key={value}>{value}</option>)}</select></div>
        <form className="compact-admin-form holiday-form" onSubmit={saveHoliday}><input name="holiday_date" type="date" required /><input name="name" required placeholder="Название дня" /><select name="kind"><option value="holiday">Выходной</option><option value="working">Рабочий перенос</option><option value="shortened">Сокращённый</option></select><button className="primary-button">Сохранить</button></form>
        <div className="simple-list scroll-list">{holidays.map((item) => <div key={item.holiday_date}><span><strong>{new Date(`${item.holiday_date}T12:00:00`).toLocaleDateString("ru-RU", { day: "numeric", month: "long" })}</strong><small>{item.name}</small></span><code>{item.kind}</code></div>)}</div>
      </article>
    </div>
  </section>;
}
