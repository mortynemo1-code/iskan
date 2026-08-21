import { useCallback, useEffect, useMemo, useState } from "react";
import { ProductivityReport } from "./ProductivityReport";

type ReportCode = "productivity" | "departments" | "timesheet" | "apps" | "discipline" | "absences" | "daily_activity" | "anomalies";
type ReportTable = { code: string; title: string; columns: string[]; rows: Array<Record<string, unknown>>; summary: Record<string, unknown> };
type Preset = { id: string; name: string; report_code: ReportCode; filters: Record<string, unknown>; columns: string[] | null };
type Presence = { employee_id: string | null; employee_name: string | null; hostname: string };

const reportLabels: Record<ReportCode, string> = {
  productivity: "Продуктивность", departments: "Отделы", timesheet: "Табель", apps: "Приложения и сайты",
  discipline: "Дисциплина", absences: "Отсутствия", daily_activity: "Активность за день", anomalies: "Аномалии",
};
const columnLabels: Record<string, string> = {
  rank: "Место", employee_name: "Сотрудник", department_name: "Отдел", employees: "Сотрудников",
  plan_hours: "План, ч", fact_hours: "Факт, ч", deviation_hours: "Отклонение, ч", online_hours: "Онлайн, ч",
  productive_hours: "Работа, ч", neutral_hours: "Нейтрально, ч", unproductive_hours: "Непродуктивно, ч", idle_hours: "Простой, ч",
  productive_percent: "Продуктивность, %", baseline_percent: "Среднее 14 дней, %", drop_pp: "Падение, п.п.",
  kind: "Вид", item: "Приложение / сайт", category: "Категория", productivity: "Класс", hours: "Часы",
  late_valid: "Опоздания уваж.", late_invalid: "Опоздания наруш.", late_minutes: "Минуты опозданий", early_leaves: "Ранние уходы",
  absences_unexcused: "Прогулы", violations: "Нарушения", severity_points: "Баллы серьёзности", type_name: "Тип",
  date_from: "С", date_to: "По", days: "Дней", status: "Статус", reason: "Причина", vacation_balance: "Остаток отпуска",
  day: "Дата", ts_start: "Начало", ts_end: "Конец", duration_sec: "Секунд", state: "Состояние", application: "Приложение",
  window_title: "Окно", url_domain: "Домен", screenshot_url: "Скриншот",
};

function dateInput(offsetDays = 0): string { const value = new Date(); value.setDate(value.getDate() + offsetDays); value.setMinutes(value.getMinutes() - value.getTimezoneOffset()); return value.toISOString().slice(0, 10); }
function formatCell(value: unknown): string { if (value === null || value === undefined) return "—"; if (typeof value === "object") return JSON.stringify(value); return String(value); }

export function ReportsHub({ onSelectEmployee }: { onSelectEmployee: (id: string) => void }) {
  const [code, setCode] = useState<ReportCode>("productivity");
  const [from, setFrom] = useState(dateInput(-30)); const [to, setTo] = useState(dateInput());
  const [month, setMonth] = useState(dateInput().slice(0, 7)); const [employeeId, setEmployeeId] = useState("");
  const [onlyUnproductive, setOnlyUnproductive] = useState(false); const [dropPp, setDropPp] = useState(20);
  const [table, setTable] = useState<ReportTable | null>(null); const [visibleColumns, setVisibleColumns] = useState<string[]>([]);
  const [sort, setSort] = useState<{ column: string; direction: 1 | -1 } | null>(null); const [page, setPage] = useState(1);
  const [presets, setPresets] = useState<Preset[]>([]); const [presence, setPresence] = useState<Presence[]>([]);
  const [presetName, setPresetName] = useState(""); const [recipients, setRecipients] = useState("");
  const [message, setMessage] = useState<string | null>(null); const [loading, setLoading] = useState(false);

  const filters = useMemo<Record<string, unknown>>(() => code === "timesheet" ? { month } : code === "daily_activity" ? { employee_id: employeeId, day: from } : { from, to, ...(code === "apps" ? { only_unproductive: onlyUnproductive } : {}), ...(code === "anomalies" ? { drop_pp: dropPp } : {}) }, [code, dropPp, employeeId, from, month, onlyUnproductive, to]);

  const loadMeta = useCallback(async () => {
    const [presetResponse, presenceResponse] = await Promise.all([fetch("/api/v1/report-presets"), fetch("/api/v1/presence")]);
    if (presetResponse.ok) setPresets(await presetResponse.json()); if (presenceResponse.ok) setPresence(await presenceResponse.json());
  }, []);
  useEffect(() => { void loadMeta(); }, [loadMeta]);

  const load = useCallback(async () => {
    if (code === "productivity" || (code === "daily_activity" && !employeeId)) return;
    setLoading(true); setMessage(null);
    const params = new URLSearchParams(); Object.entries(filters).forEach(([key, value]) => params.set(key === "from" || key === "to" ? key : key, String(value)));
    const urlCode = code === "daily_activity" ? "daily-activity" : code;
    try {
      const response = await fetch(`/api/v1/reports/${urlCode}?${params}`); if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body: ReportTable = await response.json(); setTable(body); setVisibleColumns(body.columns); setPage(1);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Ошибка отчёта"); }
    finally { setLoading(false); }
  }, [code, employeeId, filters]);
  useEffect(() => { void load(); }, [load]);

  const sortedRows = useMemo(() => {
    if (!table || !sort) return table?.rows ?? [];
    return [...table.rows].sort((a, b) => String(a[sort.column] ?? "").localeCompare(String(b[sort.column] ?? ""), "ru", { numeric: true }) * sort.direction);
  }, [sort, table]);
  const pageRows = sortedRows.slice((page - 1) * 50, page * 50); const pages = Math.max(1, Math.ceil(sortedRows.length / 50));

  const exportReport = async (format: "csv" | "xlsx" | "pdf") => {
    const response = await fetch(`/api/v1/reports/${code}/export`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ format, filters, columns: visibleColumns }) });
    if (!response.ok) { setMessage(`Экспорт не выполнен: HTTP ${response.status}`); return; }
    const blob = await response.blob(); const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${code}.${format}`; anchor.click(); URL.revokeObjectURL(url);
  };
  const savePreset = async () => {
    if (!presetName) return; const response = await fetch("/api/v1/report-presets", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: presetName, report_code: code, filters, columns: visibleColumns }) });
    if (response.ok) { setPresetName(""); setMessage("Пресет сохранён"); await loadMeta(); }
  };
  const schedule = async () => {
    const emails = recipients.split(/[;,\s]+/).filter(Boolean); if (!emails.length) return;
    const response = await fetch("/api/v1/report-schedules", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ report_code: code, filters, recipients: emails, cron: "0 8 * * 1", format: "xlsx", enabled: true }) });
    setMessage(response.ok ? "Еженедельная рассылка назначена на понедельник 08:00" : `Ошибка расписания: HTTP ${response.status}`);
  };
  const applyPreset = (preset: Preset) => {
    setCode(preset.report_code); const current = preset.filters; if (current.from) setFrom(String(current.from)); if (current.to) setTo(String(current.to)); if (current.month) setMonth(String(current.month)); if (current.employee_id) setEmployeeId(String(current.employee_id)); if (preset.columns) setVisibleColumns(preset.columns);
  };

  return <section className="reports-hub">
    <header className="dashboard-heading"><div><p className="eyebrow">Аналитика</p><h1>Отчёты</h1><p>Время, активность, дисциплина и кадровые события</p></div></header>
    <nav className="report-tabs">{(Object.keys(reportLabels) as ReportCode[]).map((item) => <button className={code === item ? "active" : ""} key={item} onClick={() => setCode(item)}>{reportLabels[item]}</button>)}</nav>
    {code === "productivity" ? <ProductivityReport onSelectEmployee={onSelectEmployee} /> : <>
      <div className="report-control-panel">
        {code === "timesheet" ? <label><span>Месяц</span><input type="month" value={month} onChange={(event) => setMonth(event.target.value)} /></label> : <><label><span>С</span><input type="date" value={from} onChange={(event) => setFrom(event.target.value)} /></label>{code !== "daily_activity" && <label><span>По</span><input type="date" value={to} onChange={(event) => setTo(event.target.value)} /></label>}</>}
        {code === "daily_activity" && <label><span>Сотрудник</span><select value={employeeId} onChange={(event) => setEmployeeId(event.target.value)}><option value="">Выберите</option>{presence.filter((item) => item.employee_id).map((item) => <option value={item.employee_id!} key={item.employee_id!}>{item.employee_name ?? item.hostname}</option>)}</select></label>}
        {code === "apps" && <label className="checkbox-field"><input type="checkbox" checked={onlyUnproductive} onChange={(event) => setOnlyUnproductive(event.target.checked)} /> Только непродуктивное</label>}
        {code === "anomalies" && <label><span>Падение, п.п.</span><input type="number" min="1" max="100" value={dropPp} onChange={(event) => setDropPp(Number(event.target.value))} /></label>}
        <button className="primary-button" onClick={() => void load()}>Обновить</button>
        <div className="export-group"><button onClick={() => void exportReport("xlsx")}>XLSX</button><button onClick={() => void exportReport("csv")}>CSV</button><button onClick={() => void exportReport("pdf")}>PDF</button></div>
      </div>
      <div className="report-tools"><label><span>Пресет</span><select defaultValue="" onChange={(event) => { const preset = presets.find((item) => item.id === event.target.value); if (preset) applyPreset(preset); }}><option value="">Выберите сохранённый</option>{presets.filter((item) => item.report_code === code).map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label><label><span>Название</span><input value={presetName} onChange={(event) => setPresetName(event.target.value)} placeholder="Мой отчёт" /></label><button onClick={() => void savePreset()}>Сохранить пресет</button><label className="schedule-emails"><span>E-mail для еженедельной рассылки</span><input value={recipients} onChange={(event) => setRecipients(event.target.value)} placeholder="manager@company.ru" /></label><button onClick={() => void schedule()}>Создать рассылку</button></div>
      {table && <details className="column-picker"><summary>Видимые столбцы ({visibleColumns.length})</summary><div>{table.columns.map((column) => <label key={column}><input type="checkbox" checked={visibleColumns.includes(column)} onChange={(event) => setVisibleColumns((current) => event.target.checked ? [...current, column] : current.filter((item) => item !== column))} />{columnLabels[column] ?? (column.startsWith("d") ? column.slice(1) : column)}</label>)}</div></details>}
      {message && <div className="notice">{message}</div>}
      {loading ? <div className="dashboard-loading">Строим отчёт…</div> : table && <div className="generic-report-wrap"><table><thead><tr>{visibleColumns.map((column) => <th key={column}><button onClick={() => setSort((current) => ({ column, direction: current?.column === column ? (current.direction === 1 ? -1 : 1) : 1 }))}>{columnLabels[column] ?? (column.startsWith("d") ? column.slice(1) : column)}{sort?.column === column ? (sort.direction === 1 ? " ↑" : " ↓") : ""}</button></th>)}</tr></thead><tbody>{pageRows.map((row, index) => <tr key={index} onDoubleClick={() => typeof row.employee_id === "string" && onSelectEmployee(row.employee_id)}>{visibleColumns.map((column) => <td key={column}>{column === "screenshot_url" && row[column] ? <a href={String(row[column])} target="_blank" rel="noreferrer">Открыть</a> : formatCell(row[column])}</td>)}</tr>)}</tbody></table></div>}
      {table && <div className="report-pagination"><span>Строк: {sortedRows.length}</span><button disabled={page <= 1} onClick={() => setPage(page - 1)}>←</button><strong>{page} / {pages}</strong><button disabled={page >= pages} onClick={() => setPage(page + 1)}>→</button></div>}
    </>}
  </section>;
}
