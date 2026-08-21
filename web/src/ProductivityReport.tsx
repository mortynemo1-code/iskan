import { useEffect, useMemo, useState } from "react";

type Basis = "planned" | "online" | "active";
type ReportRow = {
  employee_id: string;
  employee_name: string;
  department_id: string | null;
  department_name: string | null;
  planned_seconds: number;
  online_seconds: number;
  productive_seconds: number;
  neutral_seconds: number;
  unproductive_seconds: number;
  idle_seconds: number;
  absence_seconds: number;
  productive_percent: number;
  unproductive_percent: number;
  idle_percent: number;
  delta_productive_pp: number;
  grade: string;
  grade_label: string;
};
type Totals = Omit<ReportRow, "employee_id" | "employee_name" | "department_id" | "department_name" | "grade" | "grade_label">;
type ReportData = { basis: Basis; rows: ReportRow[]; totals: Totals };

function localDate(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

function initialDates() {
  const now = new Date();
  const from = new Date(now.getFullYear(), now.getMonth(), 1);
  return { from: localDate(from), to: localDate(now) };
}

function apiRange(from: string, to: string) {
  const end = new Date(`${to}T00:00:00`);
  end.setDate(end.getDate() + 1);
  return { start: new Date(`${from}T00:00:00`), end };
}

function duration(seconds: number): string {
  return (seconds / 3600).toLocaleString("ru-RU", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
}

function Delta({ value }: { value: number }) {
  return <span className={`delta ${value > 0 ? "up" : value < 0 ? "down" : ""}`}>{value > 0 ? "↑" : value < 0 ? "↓" : "→"} {Math.abs(value)} п.п.</span>;
}

export function ProductivityReport({ onSelectEmployee }: { onSelectEmployee: (id: string) => void }) {
  const defaults = initialDates();
  const [from, setFrom] = useState(defaults.from);
  const [to, setTo] = useState(defaults.to);
  const [basis, setBasis] = useState<Basis>("planned");
  const [department, setDepartment] = useState("");
  const [departmentOptions, setDepartmentOptions] = useState<Array<[string, string]>>([]);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState("employee");
  const [direction, setDirection] = useState<"asc" | "desc">("asc");
  const [data, setData] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const range = apiRange(from, to);
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams({ from: range.start.toISOString(), to: range.end.toISOString(), basis, sort, direction });
        if (department) params.set("department_id", department);
        const response = await fetch(`/api/v1/reports/productivity?${params}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        if (!cancelled) {
          setData(body);
          if (!department) {
            setDepartmentOptions(Array.from(new Map<string, string>(body.rows.filter((row: ReportRow) => row.department_id).map((row: ReportRow) => [row.department_id!, row.department_name!])).entries()));
          }
          setError(null);
        }
      } catch (loadError) {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : "Ошибка загрузки");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => { cancelled = true; };
  }, [from, to, basis, sort, direction, department]);

  const rows = useMemo(() => (data?.rows ?? []).filter((row) => !query || row.employee_name.toLowerCase().includes(query.toLowerCase())), [data, query]);
  const exportParams = new URLSearchParams({ from: range.start.toISOString(), to: range.end.toISOString(), basis });
  if (department) exportParams.set("department_id", department);

  const changeSort = (field: string) => {
    if (sort === field) setDirection((current) => current === "asc" ? "desc" : "asc");
    else { setSort(field); setDirection(field === "employee" || field === "department" ? "asc" : "desc"); }
  };

  return (
    <section className="report-page">
      <header className="topbar report-heading">
        <div><p className="eyebrow">Основной отчёт</p><h1>Продуктивность сотрудников</h1></div>
        <a className="export-button" href={`/api/v1/reports/productivity.csv?${exportParams}`}>Скачать CSV</a>
      </header>

      <section className="report-filters">
        <label><span>С</span><input type="date" value={from} onChange={(event) => setFrom(event.target.value)} /></label>
        <label><span>По</span><input type="date" value={to} onChange={(event) => setTo(event.target.value)} /></label>
        <label><span>База процентов</span><select value={basis} onChange={(event) => setBasis(event.target.value as Basis)}><option value="planned">Плановое время</option><option value="online">Фактический онлайн</option><option value="active">Активное время</option></select></label>
        <label><span>Отдел</span><select value={department} onChange={(event) => setDepartment(event.target.value)}><option value="">Все отделы</option>{departmentOptions.map(([id, name]) => <option value={id} key={id}>{name}</option>)}</select></label>
        <label className="report-search"><span>Сотрудник</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Поиск по имени" /></label>
      </section>

      {error && <div className="notice notice-error">Отчёт недоступен: {error}</div>}
      <section className="report-summary">
        <span><small>Продуктивность</small><strong>{data?.totals.productive_percent ?? 0}%</strong><Delta value={data?.totals.delta_productive_pp ?? 0} /></span>
        <span><small>Работа</small><strong>{duration(data?.totals.productive_seconds ?? 0)} ч</strong></span>
        <span><small>Непродуктивно</small><strong>{duration(data?.totals.unproductive_seconds ?? 0)} ч</strong></span>
        <span><small>Простой</small><strong>{duration(data?.totals.idle_seconds ?? 0)} ч</strong></span>
      </section>

      <div className="report-table-wrap">
        <table className="report-table">
          <thead><tr>
            <th><button onClick={() => changeSort("employee")}>Сотрудник</button></th>
            <th><button onClick={() => changeSort("department")}>Отдел</button></th>
            <th>План</th><th><button onClick={() => changeSort("online")}>Онлайн</button></th><th>Работа</th><th>Нейтр.</th>
            <th>Непрод.</th><th>Простой</th><th>Отсутствия</th><th><button onClick={() => changeSort("productive")}>% работы</button></th>
            <th><button onClick={() => changeSort("unproductive")}>% непрод.</button></th><th><button onClick={() => changeSort("idle")}>% простоя</button></th><th>Динамика</th><th>Оценка</th>
          </tr></thead>
          <tbody>
            {loading && !data ? <tr><td colSpan={14} className="table-empty">Строим отчёт…</td></tr> : rows.length === 0 ? <tr><td colSpan={14} className="table-empty">Нет данных по выбранным фильтрам</td></tr> : rows.map((row) => <tr key={row.employee_id} className="clickable-row" onClick={() => onSelectEmployee(row.employee_id)}>
              <td><strong>{row.employee_name}</strong></td><td>{row.department_name ?? "—"}</td>
              <td>{duration(row.planned_seconds)}</td><td>{duration(row.online_seconds)}</td><td>{duration(row.productive_seconds)}</td><td>{duration(row.neutral_seconds)}</td>
              <td>{duration(row.unproductive_seconds)}</td><td>{duration(row.idle_seconds)}</td><td>{duration(row.absence_seconds)}</td><td><b>{row.productive_percent}%</b></td><td>{row.unproductive_percent}%</td><td>{row.idle_percent}%</td>
              <td><Delta value={row.delta_productive_pp} /></td><td><span className={`grade grade-${row.grade.toLowerCase()}`}>{row.grade_label}</span></td>
            </tr>)}
          </tbody>
          {data && <tfoot><tr><td><strong>Итого</strong></td><td>{rows.length} сотрудников</td><td>{duration(data.totals.planned_seconds)}</td><td>{duration(data.totals.online_seconds)}</td><td>{duration(data.totals.productive_seconds)}</td><td>{duration(data.totals.neutral_seconds)}</td><td>{duration(data.totals.unproductive_seconds)}</td><td>{duration(data.totals.idle_seconds)}</td><td>{duration(data.totals.absence_seconds)}</td><td><strong>{data.totals.productive_percent}%</strong></td><td>{data.totals.unproductive_percent}%</td><td>{data.totals.idle_percent}%</td><td><Delta value={data.totals.delta_productive_pp} /></td><td /></tr></tfoot>}
        </table>
      </div>
      <p className="report-footnote">Время показано в часах. Сравнение рассчитано с предыдущим периодом той же длительности.</p>
    </section>
  );
}
