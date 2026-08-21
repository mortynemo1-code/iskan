import { useEffect, useMemo, useState } from "react";
import { ScreenshotGallery } from "./ScreenshotGallery";
import { VideoArchive } from "./VideoArchive";
import { AbsenceCalendar } from "./AbsenceCalendar";

type ProfileTab = "overview" | "timeline" | "applications" | "screenshots" | "video" | "absences" | "devices";

type ProfileData = {
  id: string;
  full_name: string;
  email: string | null;
  department_name: string | null;
  position_title: string | null;
  hire_date: string | null;
  timezone: string;
  status: string;
  planned_daily_minutes: number;
  metrics: {
    online_seconds: number;
    productive_seconds: number;
    neutral_seconds: number;
    unproductive_seconds: number;
    idle_seconds: number;
    productive_percent: number;
    unproductive_percent: number;
    idle_percent: number;
    delta_productive_pp: number;
    grade: string;
    grade_label: string;
  };
  trend: Array<{ day: string; productive_percent: number; active_seconds: number }>;
  applications: Array<{
    key: string;
    label: string;
    kind: string;
    category_name: string | null;
    productivity: string;
    seconds: number;
    percent: number;
  }>;
  devices: Array<{
    id: string;
    hostname: string;
    os_version: string;
    agent_version: string;
    is_approved: boolean;
    last_seen: string | null;
    last_activity_state: string | null;
  }>;
  absence_summary: { approved_days: number; pending_requests: number; violations: number; late_minutes: number };
  recent_activity: Array<{
    event_uuid: string;
    ts_start: string;
    ts_end: string;
    duration_sec: number;
    state: string;
    app_name: string | null;
    process_name: string | null;
    window_title: string | null;
    url_domain: string | null;
    url_path: string | null;
    category_name: string | null;
    screenshot_id: number | null;
  }>;
};

const stateLabels: Record<string, string> = {
  PRODUCTIVE: "Работа", NEUTRAL: "Нейтрально", UNPRODUCTIVE: "Непродуктивно",
  IDLE: "Простой", LOCKED: "Заблокировано", BREAK: "Личное время",
};

function hours(seconds: number): string {
  return `${(seconds / 3600).toLocaleString("ru-RU", { maximumFractionDigits: 1 })} ч`;
}

function profileRange() {
  const end = new Date();
  end.setHours(24, 0, 0, 0);
  const start = new Date(end);
  start.setDate(start.getDate() - 30);
  return { start, end };
}

export function EmployeeProfile({ employeeId, onBack, permissions }: { employeeId: string; onBack: () => void; permissions: string[] }) {
  const [data, setData] = useState<ProfileData | null>(null);
  const requestedTab = new URLSearchParams(window.location.search).get("tab") as ProfileTab | null;
  const [tab, setTab] = useState<ProfileTab>(requestedTab && ["overview","timeline","applications","screenshots","video","absences","devices"].includes(requestedTab) ? requestedTab : "overview");
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const { start, end } = profileRange();
    const load = async () => {
      try {
        const response = await fetch(`/api/v1/employees/${employeeId}/overview?from=${encodeURIComponent(start.toISOString())}&to=${encodeURIComponent(end.toISOString())}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        if (!cancelled) { setData(body); setError(null); }
      } catch (loadError) {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : "Ошибка загрузки");
      }
    };
    void load();
    return () => { cancelled = true; };
  }, [employeeId]);

  const maxAppSeconds = useMemo(() => Math.max(1, ...(data?.applications.map((item) => item.seconds) ?? [1])), [data]);

  const exportData = async () => {
    setActionMessage("Формируем архив…");
    const response = await fetch(`/api/v1/employees/${employeeId}/export`, { method: "POST" });
    if (!response.ok) { setActionMessage(`Выгрузка не выполнена: HTTP ${response.status}`); return; }
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement("a"); link.href = url; link.download = `employee-${employeeId}.zip`; link.click(); URL.revokeObjectURL(url);
    setActionMessage("Архив данных сформирован, действие записано в аудит.");
  };

  const deleteData = async () => {
    const confirmation = window.prompt(`Операция безвозвратно удалит мониторинговые данные. Введите UUID сотрудника:\n${employeeId}`);
    if (confirmation !== employeeId) { setActionMessage("Удаление отменено: подтверждение не совпало."); return; }
    const response = await fetch(`/api/v1/employees/${employeeId}/data?confirm=${encodeURIComponent(confirmation)}`, { method: "DELETE" });
    if (!response.ok) { setActionMessage(`Удаление не выполнено: HTTP ${response.status}`); return; }
    setActionMessage("Данные удалены, действие сохранено в неизменяемом аудите.");
    window.setTimeout(onBack, 1200);
  };

  if (error) return <section className="employee-profile"><button className="back-link" onClick={onBack}>← Назад</button><div className="notice notice-error">Карточка недоступна: {error}</div></section>;
  if (!data) return <div className="dashboard-loading">Загружаем карточку сотрудника…</div>;

  const tabs: Array<[ProfileTab, string]> = [
    ["overview", "Обзор"], ["timeline", "Таймлайн"], ["applications", "Приложения и сайты"],
    ...(permissions.includes("screenshot:view") ? [["screenshots", "Скриншоты"] as [ProfileTab, string]] : []),
    ...(permissions.includes("stream:archive") ? [["video", "Видеозаписи"] as [ProfileTab, string]] : []),
    ["absences", "Отсутствия"], ["devices", "Устройства"],
  ];

  return (
    <section className="employee-profile">
      <button className="back-link" onClick={onBack}>← К команде</button>
      <header className="profile-header">
        <div className="profile-avatar">{data.full_name.split(" ").map((part) => part[0]).slice(0, 2).join("")}</div>
        <div><p className="eyebrow">Карточка сотрудника</p><h1>{data.full_name}</h1><p>{[data.position_title, data.department_name, data.email].filter(Boolean).join(" · ")}</p></div>
        {permissions.includes("settings:manage") && <div className="profile-data-actions"><button onClick={() => void exportData()}>Выгрузить данные</button><button className="danger" onClick={() => void deleteData()}>Удалить данные</button></div>}
        <span className={`profile-status ${data.status}`}>{data.status === "active" ? "Активен" : "Отключён"}</span>
      </header>
      {actionMessage && <div className="notice">{actionMessage}</div>}
      <nav className="profile-tabs">{tabs.map(([value, label]) => <button className={tab === value ? "active" : ""} key={value} onClick={() => { setTab(value); window.history.replaceState({}, "", `?view=employee&employee=${employeeId}&tab=${value}`); }}>{label}</button>)}</nav>

      {tab === "overview" && <>
        <section className="profile-kpis">
          <article><span>Продуктивность</span><strong>{data.metrics.productive_percent}%</strong><small className={data.metrics.delta_productive_pp >= 0 ? "positive" : "negative"}>{data.metrics.delta_productive_pp >= 0 ? "↑" : "↓"} {Math.abs(data.metrics.delta_productive_pp)} п.п.</small></article>
          <article><span>Онлайн</span><strong>{hours(data.metrics.online_seconds)}</strong><small>за 30 дней</small></article>
          <article><span>Непродуктивно</span><strong>{hours(data.metrics.unproductive_seconds)}</strong><small>{data.metrics.unproductive_percent}% активного времени</small></article>
          <article><span>Простой</span><strong>{hours(data.metrics.idle_seconds)}</strong><small>{data.metrics.idle_percent}% базы</small></article>
          <article><span>Оценка</span><strong className={`grade-text grade-${data.metrics.grade.toLowerCase()}`}>{data.metrics.grade_label}</strong><small>план {data.planned_daily_minutes / 60} ч/день</small></article>
        </section>
        <section className="profile-overview-grid">
          <article className="dashboard-card profile-trend-card"><div className="card-heading"><span>Тренд за 30 дней</span><small>Продуктивность по дням</small></div><div className="profile-trend">{data.trend.map((point) => <div key={point.day} className="profile-trend-column"><i style={{ height: `${Math.max(3, point.productive_percent)}%` }} className={point.productive_percent >= 75 ? "good" : point.productive_percent >= 50 ? "attention" : "risk"}><span>{point.productive_percent}%</span></i><small>{new Date(point.day).toLocaleDateString("ru-RU", { day: "numeric", month: "short" })}</small></div>)}</div></article>
          <article className="dashboard-card discipline-card"><div className="card-heading"><span>Дисциплина</span><small>За период</small></div><div className="discipline-grid"><span><strong>{data.absence_summary.approved_days}</strong><small>дней отсутствий</small></span><span><strong>{data.absence_summary.pending_requests}</strong><small>на согласовании</small></span><span><strong>{data.absence_summary.violations}</strong><small>нарушений</small></span><span><strong>{data.absence_summary.late_minutes}</strong><small>минут опозданий</small></span></div></article>
        </section>
        <section className="dashboard-card profile-app-preview"><div className="card-heading"><span>Основные приложения и сайты</span><button onClick={() => setTab("applications")}>Показать все</button></div><div className="usage-list">{data.applications.slice(0, 6).map((item) => <div className="usage-row" key={`${item.kind}-${item.key}`}><span className={`usage-icon ${item.kind}`}>{item.kind === "site" ? "WWW" : "APP"}</span><span><strong>{item.key}</strong><small>{item.category_name ?? "Без категории"}</small></span><div><i className={`usage-${item.productivity.toLowerCase()}`} style={{ width: `${(item.seconds / maxAppSeconds) * 100}%` }} /></div><b>{hours(item.seconds)}</b></div>)}</div></section>
      </>}

      {tab === "timeline" && <section className="dashboard-card activity-detail"><div className="card-heading"><span>Последние события</span><small>{data.timezone}</small></div>{data.recent_activity.map((event) => <article key={event.event_uuid} className="activity-event"><time>{new Date(event.ts_start).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" })}</time><i className={`segment-${event.state.toLowerCase()}`} /><span><strong>{event.app_name ?? event.process_name ?? stateLabels[event.state]}</strong><small>{[event.window_title, event.url_domain, event.url_path].filter(Boolean).join(" · ")}</small></span><em>{event.category_name ?? stateLabels[event.state]}</em><b>{Math.round(event.duration_sec / 60)} мин</b></article>)}</section>}

      {tab === "applications" && <section className="dashboard-card profile-app-preview"><div className="card-heading"><span>Приложения и сайты</span><small>Топ по активному времени</small></div><div className="usage-list">{data.applications.map((item) => <div className="usage-row" key={`${item.kind}-${item.key}`}><span className={`usage-icon ${item.kind}`}>{item.kind === "site" ? "WWW" : "APP"}</span><span><strong>{item.key}</strong><small>{item.label} · {item.category_name ?? "Без категории"}</small></span><div><i className={`usage-${item.productivity.toLowerCase()}`} style={{ width: `${(item.seconds / maxAppSeconds) * 100}%` }} /></div><b>{hours(item.seconds)} · {item.percent}%</b></div>)}</div></section>}

      {tab === "devices" && <section className="profile-device-grid">{data.devices.map((device) => <article className="dashboard-card profile-device" key={device.id}><div className="device-icon">PC</div><div><strong>{device.hostname}</strong><span>{device.os_version}</span><small>Агент {device.agent_version}</small></div><em className={device.last_seen ? "online" : ""}>{device.last_activity_state ?? "OFFLINE"}</em><time>{device.last_seen ? new Date(device.last_seen).toLocaleString("ru-RU") : "Не подключался"}</time></article>)}</section>}

      {tab === "absences" && <AbsenceCalendar employeeId={employeeId} canManage={permissions.includes("absence:manage")} />}
      {tab === "screenshots" && <ScreenshotGallery employeeId={employeeId} canExport={permissions.includes("screenshot:export")} />}
      {tab === "video" && <VideoArchive employeeId={employeeId} />}
    </section>
  );
}
