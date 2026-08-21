import { useEffect, useMemo, useState } from "react";

type DashboardData = {
  range_start: string;
  range_end: string;
  kpis: {
    online_now: number;
    employees: number;
    productivity_percent: number;
    tracked_seconds: number;
    low_productivity: number;
  };
  departments: Array<{
    department_id: string | null;
    department_name: string;
    employees: number;
    productive_seconds: number;
    neutral_seconds: number;
    unproductive_seconds: number;
    idle_seconds: number;
    productivity_percent: number;
  }>;
  top_employees: EmployeeScore[];
  bottom_employees: EmployeeScore[];
  trend: Array<{
    day: string;
    productive_percent: number;
    productive_seconds: number;
    active_seconds: number;
  }>;
  alerts: string[];
};

type EmployeeScore = {
  employee_id: string;
  employee_name: string;
  department_name: string | null;
  productive_percent: number;
  tracked_seconds: number;
  grade: string;
};

type Period = "today" | "week" | "month";

function periodRange(period: Period): { from: Date; to: Date } {
  const to = new Date();
  to.setHours(24, 0, 0, 0);
  const from = new Date(to);
  from.setDate(from.getDate() - (period === "today" ? 1 : period === "week" ? 7 : 30));
  return { from, to };
}

function hours(seconds: number): string {
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(seconds / 3600);
}

function TrendChart({ points }: { points: DashboardData["trend"] }) {
  if (points.length === 0) return <div className="chart-empty">Недостаточно данных для тренда</div>;
  const width = 700;
  const height = 180;
  const x = (index: number) => points.length === 1 ? width / 2 : (index / (points.length - 1)) * width;
  const y = (value: number) => height - (Math.min(100, Math.max(0, value)) / 100) * height;
  const polyline = points.map((point, index) => `${x(index)},${y(point.productive_percent)}`).join(" ");
  return (
    <div className="trend-chart">
      <svg viewBox={`-8 -12 ${width + 16} ${height + 36}`} role="img" aria-label="Тренд продуктивности">
        {[0, 25, 50, 75, 100].map((value) => <line key={value} x1="0" x2={width} y1={y(value)} y2={y(value)} className="trend-grid" />)}
        <line x1="0" x2={width} y1={y(75)} y2={y(75)} className="trend-target" />
        <polyline points={polyline} className="trend-line" />
        {points.map((point, index) => <circle key={point.day} cx={x(index)} cy={y(point.productive_percent)} r="4" className="trend-dot"><title>{point.day}: {point.productive_percent}%</title></circle>)}
      </svg>
      <div className="trend-labels"><span>{new Date(points[0].day).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}</span><span>Цель 75%</span><span>{new Date(points.at(-1)!.day).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}</span></div>
    </div>
  );
}

function RatingList({ title, items, direction, onSelectEmployee }: { title: string; items: EmployeeScore[]; direction: "top" | "bottom"; onSelectEmployee: (id: string) => void }) {
  return (
    <section className="dashboard-card rating-card">
      <div className="card-heading"><span>{title}</span><em>{direction === "top" ? "↑" : "↓"}</em></div>
      {items.length === 0 ? <p className="chart-empty small">Нет активности</p> : items.map((item, index) => (
        <article className="rating-row clickable-row" key={item.employee_id} onClick={() => onSelectEmployee(item.employee_id)}>
          <strong className="rank">{index + 1}</strong>
          <span><strong>{item.employee_name}</strong><small>{item.department_name ?? "Без отдела"} · {hours(item.tracked_seconds)} ч</small></span>
          <b className={`score score-${item.grade.toLowerCase()}`}>{item.productive_percent}%</b>
        </article>
      ))}
    </section>
  );
}

export function Dashboard({ onSelectEmployee }: { onSelectEmployee: (id: string) => void }) {
  const [period, setPeriod] = useState<Period>("week");
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const { from, to } = periodRange(period);
    const load = async () => {
      setLoading(true);
      try {
        const response = await fetch(`/api/v1/dashboard?from=${encodeURIComponent(from.toISOString())}&to=${encodeURIComponent(to.toISOString())}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        if (!cancelled) { setData(body); setError(null); }
      } catch (loadError) {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : "Ошибка загрузки");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => { cancelled = true; };
  }, [period]);

  const maxDepartmentSeconds = useMemo(() => Math.max(1, ...(data?.departments.map((department) => department.productive_seconds + department.neutral_seconds + department.unproductive_seconds + department.idle_seconds) ?? [1])), [data]);

  return (
    <section className="dashboard-page">
      <header className="topbar dashboard-heading">
        <div><p className="eyebrow">Обзор команды</p><h1>Дашборд</h1></div>
        <div className="period-switch">{(["today", "week", "month"] as const).map((value) => <button className={period === value ? "active" : ""} key={value} onClick={() => setPeriod(value)}>{{ today: "Сегодня", week: "7 дней", month: "30 дней" }[value]}</button>)}</div>
      </header>

      {error && <div className="notice notice-error">Дашборд недоступен: {error}</div>}
      {loading && !data ? <div className="dashboard-loading">Собираем показатели…</div> : data && <>
        <section className="dashboard-kpis">
          <article className="dashboard-kpi live-kpi"><span>Сейчас онлайн</span><strong>{data.kpis.online_now}</strong><small>из {data.kpis.employees} сотрудников</small></article>
          <article className="dashboard-kpi"><span>Продуктивность</span><strong>{data.kpis.productivity_percent}%</strong><small>от активного времени</small></article>
          <article className="dashboard-kpi"><span>Учтено времени</span><strong>{hours(data.kpis.tracked_seconds)} ч</strong><small>за выбранный период</small></article>
          <article className={`dashboard-kpi ${data.kpis.low_productivity ? "warning-kpi" : ""}`}><span>Требуют внимания</span><strong>{data.kpis.low_productivity}</strong><small>продуктивность ниже 50%</small></article>
        </section>

        <section className="dashboard-main-grid">
          <article className="dashboard-card department-chart-card">
            <div className="card-heading"><span>Отделы</span><small>Распределение учтённого времени</small></div>
            {data.departments.length === 0 ? <p className="chart-empty">Нет данных по отделам</p> : data.departments.map((department) => {
              const total = department.productive_seconds + department.neutral_seconds + department.unproductive_seconds + department.idle_seconds;
              const scale = (total / maxDepartmentSeconds) * 100;
              return <div className="department-bar-row" key={department.department_id ?? "none"}>
                <div className="department-label"><strong>{department.department_name}</strong><small>{department.employees} чел. · {department.productivity_percent}% работы</small></div>
                <div className="stacked-bar-space"><div className="stacked-bar" style={{ width: `${scale}%` }}>
                  {(["productive", "neutral", "unproductive", "idle"] as const).map((state) => <i key={state} className={`bar-${state}`} style={{ width: `${total ? (department[`${state}_seconds`] / total) * 100 : 0}%` }} title={`${state}: ${hours(department[`${state}_seconds`])} ч`} />)}
                </div></div>
                <b>{hours(total)} ч</b>
              </div>;
            })}
            <div className="bar-legend"><span><i className="bar-productive" />Работа</span><span><i className="bar-neutral" />Нейтрально</span><span><i className="bar-unproductive" />Непродуктивно</span><span><i className="bar-idle" />Простой</span></div>
          </article>

          <article className="dashboard-card alerts-card">
            <div className="card-heading"><span>Сигналы</span><em>{data.alerts.length}</em></div>
            {data.alerts.length === 0 ? <div className="all-clear"><i>✓</i><strong>Всё спокойно</strong><span>Критичных отклонений не найдено</span></div> : data.alerts.map((alert) => <div className="alert-row" key={alert}><i>!</i><span>{alert}</span></div>)}
          </article>
        </section>

        <section className="dashboard-card trend-card">
          <div className="card-heading"><span>Динамика продуктивности</span><small>Доля продуктивного времени по дням</small></div>
          <TrendChart points={data.trend} />
        </section>

        <section className="ratings-grid">
          <RatingList title="Топ сотрудников" items={data.top_employees} direction="top" onSelectEmployee={onSelectEmployee} />
          <RatingList title="Зона внимания" items={data.bottom_employees} direction="bottom" onSelectEmployee={onSelectEmployee} />
        </section>
      </>}
    </section>
  );
}
