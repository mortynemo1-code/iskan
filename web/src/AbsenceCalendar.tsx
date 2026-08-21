import { useCallback, useEffect, useMemo, useState } from "react";

type AbsenceType = { id: number; code: string; name: string; color: string; effect: string; requires_document: boolean };
type EventItem = { id: string; employee_id: string; type_id: number; type_code: string; type_name: string; color: string; date_from: string; date_to: string; minutes: number | null; reason: string | null; comment: string | null; status: string; is_auto: boolean; severity: number | null };
type CalendarEmployee = { employee_id: string; full_name: string; department_name: string | null; events: EventItem[] };
type CalendarData = { month: string; days: number; employees: CalendarEmployee[] };

function monthValue(): string { const now = new Date(); now.setMinutes(now.getMinutes() - now.getTimezoneOffset()); return now.toISOString().slice(0, 7); }
function isoDay(month: string, day: number): string { return `${month}-${String(day).padStart(2, "0")}`; }

export function AbsenceCalendar({ canManage, employeeId }: { canManage: boolean; employeeId?: string }) {
  const [month, setMonth] = useState(monthValue);
  const [data, setData] = useState<CalendarData | null>(null);
  const [types, setTypes] = useState<AbsenceType[]>([]);
  const [selectedEmployees, setSelectedEmployees] = useState<Set<string>>(new Set(employeeId ? [employeeId] : []));
  const [startDay, setStartDay] = useState<number | null>(null);
  const [endDay, setEndDay] = useState<number | null>(null);
  const [dragEmployee, setDragEmployee] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [typeId, setTypeId] = useState(0);
  const [reason, setReason] = useState("");
  const [minutes, setMinutes] = useState("");
  const [severity, setSeverity] = useState("");
  const [status, setStatus] = useState(canManage ? "approved" : "pending");
  const [activeEvent, setActiveEvent] = useState<EventItem | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [calendarResponse, typeResponse] = await Promise.all([fetch(`/api/v1/calendar?month=${month}`), fetch("/api/v1/absence-types")]);
    if (calendarResponse.ok) {
      const body: CalendarData = await calendarResponse.json();
      if (employeeId) body.employees = body.employees.filter((item) => item.employee_id === employeeId);
      setData(body);
    }
    if (typeResponse.ok) {
      const body: AbsenceType[] = await typeResponse.json(); setTypes(body); if (!typeId && body[0]) setTypeId(body[0].id);
    }
  }, [employeeId, month, typeId]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => {
    const stop = () => setDragging(false); window.addEventListener("pointerup", stop); return () => window.removeEventListener("pointerup", stop);
  }, []);

  const selectedType = types.find((item) => item.id === typeId);
  const normalized = useMemo(() => startDay === null || endDay === null ? null : { from: Math.min(startDay, endDay), to: Math.max(startDay, endDay) }, [startDay, endDay]);

  const create = async () => {
    if (!normalized || selectedEmployees.size === 0 || !typeId) return;
    const response = await fetch("/api/v1/absences", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
      employee_ids: [...selectedEmployees], type_id: typeId, date_from: isoDay(month, normalized.from), date_to: isoDay(month, normalized.to),
      minutes: minutes ? Number(minutes) : null, reason: reason || null, severity: severity ? Number(severity) : null, status,
    }) });
    if (!response.ok) { const body = await response.json().catch(() => ({})); setMessage(body.detail ?? `HTTP ${response.status}`); return; }
    setMessage(canManage && status === "approved" ? "Событие добавлено в календарь" : "Заявка отправлена на согласование");
    setStartDay(null); setEndDay(null); setReason(""); setMinutes(""); setSeverity(""); await load();
  };

  const decide = async (decision: "approve" | "reject") => {
    if (!activeEvent) return;
    const response = await fetch(`/api/v1/absences/${activeEvent.id}/${decision}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ comment: null }) });
    if (response.ok) { setActiveEvent(null); await load(); } else setMessage(`Не удалось принять решение: HTTP ${response.status}`);
  };

  const toggleEmployee = (id: string) => setSelectedEmployees((current) => { const next = new Set(current); if (next.has(id)) next.delete(id); else next.add(id); return next; });

  return <section className="absence-page">
    {!employeeId && <header className="dashboard-heading"><div><p className="eyebrow">Кадровые события</p><h1>Календарь отсутствий</h1><p>Отпуска, больничные, командировки и нарушения</p></div><label className="month-picker"><span>Месяц</span><input type="month" value={month} onChange={(event) => { setMonth(event.target.value); setStartDay(null); setEndDay(null); }} /></label></header>}
    {employeeId && <label className="month-picker inline"><span>Месяц</span><input type="month" value={month} onChange={(event) => setMonth(event.target.value)} /></label>}
    {message && <div className="notice">{message}</div>}
    {!data ? <div className="dashboard-loading">Загружаем календарь…</div> : <div className="absence-calendar-wrap"><div className="absence-calendar" style={{ gridTemplateColumns: `220px repeat(${data.days}, minmax(28px, 1fr))` }}>
      <div className="calendar-corner">Сотрудник</div>
      {Array.from({ length: data.days }, (_, index) => index + 1).map((day) => { const date = new Date(`${isoDay(month, day)}T12:00:00`); const weekend = date.getDay() === 0 || date.getDay() === 6; return <div className={`calendar-day-head ${weekend ? "weekend" : ""}`} key={day}><strong>{day}</strong><small>{date.toLocaleDateString("ru-RU", { weekday: "short" }).slice(0, 2)}</small></div>; })}
      {data.employees.map((employee) => <div className="calendar-row-fragment" key={employee.employee_id} style={{ display: "contents" }}>
        <label className="calendar-employee"><input type="checkbox" checked={selectedEmployees.has(employee.employee_id)} onChange={() => toggleEmployee(employee.employee_id)} disabled={Boolean(employeeId)} /><span><strong>{employee.full_name}</strong><small>{employee.department_name ?? "Без отдела"}</small></span></label>
        {Array.from({ length: data.days }, (_, index) => index + 1).map((day) => {
          const currentDate = isoDay(month, day); const item = employee.events.find((event) => event.date_from <= currentDate && event.date_to >= currentDate && event.status !== "rejected");
          const selected = selectedEmployees.has(employee.employee_id) && normalized && day >= normalized.from && day <= normalized.to;
          return <button key={day} className={`calendar-cell ${selected ? "selected" : ""} ${item ? "has-event" : ""}`} style={item ? { backgroundColor: `${item.color}2d`, borderColor: item.color } : undefined}
            title={item ? `${item.type_name} · ${item.status}${item.is_auto ? " · авто" : ""}` : "Выделить период"}
            onPointerDown={() => { setDragging(true); setDragEmployee(employee.employee_id); setSelectedEmployees(new Set([employee.employee_id])); setStartDay(day); setEndDay(day); }}
            onPointerEnter={() => { if (dragging && dragEmployee === employee.employee_id) setEndDay(day); }}
            onClick={() => { if (item) setActiveEvent(item); }}>{item && <i style={{ background: item.color }}>{item.is_auto ? "A" : ""}</i>}</button>;
        })}
      </div>)}
    </div></div>}
    {normalized && <div className="absence-create-panel">
      <div><strong>{isoDay(month, normalized.from)} — {isoDay(month, normalized.to)}</strong><small>Сотрудников: {selectedEmployees.size}. Можно отметить дополнительные строки.</small></div>
      <label><span>Тип события</span><select value={typeId} onChange={(event) => setTypeId(Number(event.target.value))}>{types.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
      {(selectedType?.code.startsWith("LATE") || selectedType?.code === "EARLY_LEAVE" || selectedType?.code === "OVERTIME") && <label><span>Минуты</span><input type="number" min="1" max="1440" value={minutes} onChange={(event) => setMinutes(event.target.value)} /></label>}
      {selectedType?.code === "VIOLATION" && <label><span>Серьёзность</span><select value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="">Выберите</option>{[1,2,3,4,5].map((value) => <option key={value}>{value}</option>)}</select></label>}
      <label className="absence-reason"><span>Причина / номер документа</span><input value={reason} onChange={(event) => setReason(event.target.value)} placeholder={selectedType?.requires_document ? "Обязательно для согласования" : "Необязательно"} /></label>
      {canManage && <label><span>Статус</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="approved">Сразу одобрено</option><option value="pending">На согласование</option><option value="draft">Черновик</option></select></label>}
      <button className="primary-button" onClick={() => void create()}>Создать</button><button className="secondary-button" onClick={() => { setStartDay(null); setEndDay(null); }}>Отмена</button>
    </div>}
    {activeEvent && <div className="event-popover"><button className="event-close" onClick={() => setActiveEvent(null)}>×</button><i style={{ background: activeEvent.color }} /><h3>{activeEvent.type_name}</h3><p>{activeEvent.date_from} — {activeEvent.date_to}</p><p>{activeEvent.reason ?? "Причина не указана"}</p><span className={`event-status ${activeEvent.status}`}>{activeEvent.status}{activeEvent.is_auto ? " · авто" : ""}</span>{canManage && ["draft", "pending"].includes(activeEvent.status) && <footer><button onClick={() => void decide("reject")}>Отклонить</button><button onClick={() => void decide("approve")}>Одобрить</button></footer>}</div>}
  </section>;
}
