import { useEffect, useMemo, useState } from "react";
import { AdminPanel } from "./AdminPanel";
import { LoginScreen, type UserInfo } from "./LoginScreen";
import { Dashboard } from "./Dashboard";
import { ReportsHub } from "./ReportsHub";
import { EmployeeProfile } from "./EmployeeProfile";
import { LiveWall } from "./LiveWall";
import { VideoArchive } from "./VideoArchive";
import { AbsenceCalendar } from "./AbsenceCalendar";
import { NotificationBell } from "./NotificationBell";
import { TeamTimelineCanvas, type TimelineAction } from "./TeamTimelineCanvas";

type PresenceStatus =
  | "ONLINE"
  | "OFFLINE"
  | "PRODUCTIVE"
  | "NEUTRAL"
  | "UNPRODUCTIVE"
  | "IDLE"
  | "LOCKED"
  | "BREAK";

type PresenceItem = {
  device_id: string;
  employee_id: string | null;
  employee_name: string | null;
  department_name: string | null;
  hostname: string;
  is_approved: boolean;
  is_online: boolean;
  status: PresenceStatus;
  last_seen: string | null;
  seconds_since_seen: number | null;
};

type Filter = "all" | "online" | "offline" | "idle";

type TimelineSegment = {
  event_uuid: string;
  ts_start: string;
  ts_end: string;
  duration_sec: number;
  state: PresenceStatus;
  app_name: string | null;
  process_name: string | null;
  window_title: string | null;
  url_domain: string | null;
  url_path: string | null;
  category_id: number | null;
};

type EmployeeTimeline = {
  device_id: string;
  employee_id: string | null;
  employee_name: string | null;
  department_name: string | null;
  hostname: string;
  segments: TimelineSegment[];
  totals: {
    productive: number;
    neutral: number;
    unproductive: number;
    idle: number;
    locked: number;
    break_time: number;
  };
};

type TimelineResponse = {
  range_start: string;
  range_end: string;
  employees: EmployeeTimeline[];
};

const statusLabels: Record<PresenceStatus, string> = {
  ONLINE: "Онлайн",
  OFFLINE: "Офлайн",
  PRODUCTIVE: "Работает",
  NEUTRAL: "Нейтральная активность",
  UNPRODUCTIVE: "Непродуктивная активность",
  IDLE: "Простой",
  LOCKED: "Экран заблокирован",
  BREAK: "Личное время",
};

function socketUrl(): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/v1/ws/presence`;
}

function formatLastSeen(value: string | null): string {
  if (!value) return "Ещё не подключался";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "short",
    timeStyle: "medium",
  }).format(new Date(value));
}

function todayInputValue(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

function dateRange(date: string, mode: "day" | "week" = "day"): { start: Date; end: Date } {
  const start = new Date(`${date}T00:00:00`);
  const end = new Date(start);
  end.setDate(end.getDate() + (mode === "week" ? 7 : 1));
  return { start, end };
}

function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours} ч ${minutes} мин`;
}

function AuthenticatedApp({ user, onLogout }: { user: UserInfo; onLogout: () => void }) {
  const initialQuery = new URLSearchParams(window.location.search);
  const requestedView = initialQuery.get("view");
  const initialView = (["dashboard","monitoring","live","archive","absences","reports","admin","employee"].includes(requestedView ?? "") ? requestedView : null) as "dashboard" | "monitoring" | "live" | "archive" | "absences" | "reports" | "admin" | "employee" | null;
  const [activeView, setActiveView] = useState<"dashboard" | "monitoring" | "live" | "archive" | "absences" | "reports" | "admin" | "employee">(
    initialView ?? (user.permissions.includes("reports:view") ? "dashboard" : "monitoring"),
  );
  const [selectedEmployeeId, setSelectedEmployeeId] = useState<string | null>(initialQuery.get("employee"));
  const [items, setItems] = useState<PresenceItem[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [connected, setConnected] = useState(false);
  const [selectedDate, setSelectedDate] = useState(todayInputValue);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [timelineError, setTimelineError] = useState<string | null>(null);
  const [timelineMode, setTimelineMode] = useState<"day" | "week">("day");

  const timelineAction = (action: TimelineAction, employee: { employee_id: string | null }, segment: { ts_start: string }) => {
    if (!employee.employee_id) return;
    const target = action === "video" ? "archive" : action === "screenshots" ? "employee" : action === "violation" ? "absences" : "admin";
    const tab = action === "screenshots" ? "&tab=screenshots" : "";
    window.history.pushState({}, "", `?view=${target}&employee=${employee.employee_id}&at=${encodeURIComponent(segment.ts_start)}${tab}`);
    setSelectedEmployeeId(employee.employee_id); setActiveView(target);
  };

  useEffect(() => {
    const apply = async () => {
      const response = await fetch("/api/v1/settings/appearance"); if (!response.ok) return;
      const body = await response.json(); const colors = body.color_scheme?.colors ?? {};
      Object.entries(colors).forEach(([state, color]) => document.documentElement.style.setProperty(`--state-${state.toLowerCase()}`, String(color)));
    };
    void apply(); window.addEventListener("appearance-changed", apply); return () => window.removeEventListener("appearance-changed", apply);
  }, []);

  useEffect(() => {
    if (activeView !== "monitoring") return;
    let socket: WebSocket | undefined;
    let retryTimer: number | undefined;

    const connect = () => {
      socket = new WebSocket(socketUrl());
      socket.onopen = () => setConnected(true);
      socket.onmessage = (event) => setItems(JSON.parse(event.data));
      socket.onclose = () => {
        setConnected(false);
        retryTimer = window.setTimeout(connect, 2000);
      };
    };

    connect();
    return () => {
      if (retryTimer) window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [activeView]);

  useEffect(() => {
    if (activeView !== "monitoring") return;
    let cancelled = false;
    const load = async () => {
      const { start, end } = dateRange(selectedDate, timelineMode);
      try {
        const response = await fetch(
          `/api/v1/timeline?from=${encodeURIComponent(start.toISOString())}&to=${encodeURIComponent(end.toISOString())}`,
        );
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data: TimelineResponse = await response.json();
        if (!cancelled) {
          setTimeline(data);
          setTimelineError(null);
        }
      } catch (error) {
        if (!cancelled) setTimelineError(error instanceof Error ? error.message : "Ошибка загрузки");
      }
    };
    void load();
    const timer = window.setInterval(load, 15_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [activeView, selectedDate, timelineMode]);

  const onlineCount = items.filter((item) => item.is_online).length;
  const visibleItems = useMemo(
    () =>
      items.filter((item) => {
        if (filter === "online") return item.is_online;
        if (filter === "offline") return !item.is_online;
        if (filter === "idle") return item.status === "IDLE";
        return true;
      }),
    [filter, items],
  );

  return (
    <main className="page-shell">
      <div className="app-header">
        <nav className="app-nav" aria-label="Основные разделы">
          {user.permissions.includes("reports:view") && (
            <button className={activeView === "dashboard" ? "active" : ""} onClick={() => setActiveView("dashboard")}>
              Дашборд
            </button>
          )}
          <button className={activeView === "monitoring" ? "active" : ""} onClick={() => setActiveView("monitoring")}>
            Мониторинг
          </button>
          {user.permissions.includes("stream:live") && <button className={activeView === "live" ? "active" : ""} onClick={() => setActiveView("live")}>Live</button>}
          {user.permissions.includes("stream:archive") && <button className={activeView === "archive" ? "active" : ""} onClick={() => setActiveView("archive")}>Видеоархив</button>}
          {(user.permissions.includes("absence:manage") || user.permissions.includes("absence:request")) && <button className={activeView === "absences" ? "active" : ""} onClick={() => setActiveView("absences")}>Отсутствия</button>}
          {user.permissions.includes("reports:view") && (
            <button className={activeView === "reports" ? "active" : ""} onClick={() => setActiveView("reports")}>
              Отчёты
            </button>
          )}
          {user.permissions.includes("settings:manage") && (
            <button className={activeView === "admin" ? "active" : ""} onClick={() => setActiveView("admin")}>
              Администрирование
            </button>
          )}
        </nav>
        <div className="user-menu">
          <NotificationBell />
          <span><strong>{user.display_name}</strong><small>{user.role}</small></span>
          <button onClick={onLogout}>Выйти</button>
        </div>
      </div>

      {activeView === "dashboard" ? <Dashboard onSelectEmployee={(id) => { setSelectedEmployeeId(id); setActiveView("employee"); }} /> : activeView === "reports" ? <ReportsHub onSelectEmployee={(id) => { setSelectedEmployeeId(id); setActiveView("employee"); }} /> : activeView === "live" ? <LiveWall /> : activeView === "archive" ? <VideoArchive /> : activeView === "absences" ? <AbsenceCalendar canManage={user.permissions.includes("absence:manage")} /> : activeView === "employee" && selectedEmployeeId ? <EmployeeProfile employeeId={selectedEmployeeId} permissions={user.permissions} onBack={() => setActiveView(user.permissions.includes("reports:view") ? "dashboard" : "monitoring")} /> : activeView === "admin" ? <AdminPanel currentRole={user.role} /> : <>
      <header className="topbar">
        <div>
          <p className="eyebrow">Мониторинг команды</p>
          <h1>Кто сейчас онлайн</h1>
        </div>
        <span className={`connection ${connected ? "connected" : ""}`}>
          {connected ? "Данные обновляются" : "Переподключение…"}
        </span>
      </header>

      <section className="summary" aria-label="Сводка">
        <div className="metric primary">
          <span>Сейчас онлайн</span>
          <strong>{onlineCount}</strong>
        </div>
        <div className="metric">
          <span>Всего устройств</span>
          <strong>{items.length}</strong>
        </div>
        <div className="metric">
          <span>На простое</span>
          <strong>{items.filter((item) => item.status === "IDLE").length}</strong>
        </div>
        <div className="metric">
          <span>Не подтверждены</span>
          <strong>{items.filter((item) => !item.is_approved).length}</strong>
        </div>
      </section>

      <nav className="filters" aria-label="Фильтр статуса">
        {(["all", "online", "offline", "idle"] as const).map((value) => (
          <button
            className={filter === value ? "active" : ""}
            key={value}
            onClick={() => setFilter(value)}
          >
            {{ all: "Все", online: "Онлайн", offline: "Офлайн", idle: "Простой" }[value]}
          </button>
        ))}
      </nav>

      <section className="team-list">
        {visibleItems.length === 0 ? (
          <div className="empty-state">
            <h2>Устройств пока нет</h2>
            <p>Установите и зарегистрируйте первый Windows-агент.</p>
          </div>
        ) : (
          visibleItems.map((item) => (
            <article className="employee-row" key={item.device_id}>
              <span className={`presence-dot ${item.is_online ? "online" : "offline"}`} />
              <div className="identity">
                <strong>{item.employee_name ?? item.hostname}</strong>
                <span>{item.department_name ?? (item.employee_name ? item.hostname : "Непривязанное устройство")}</span>
              </div>
              <span className={`status status-${item.status.toLowerCase()}`}>
                {statusLabels[item.status]}
              </span>
              <div className="last-seen">
                <span>{item.hostname}</span>
                <time dateTime={item.last_seen ?? undefined}>{formatLastSeen(item.last_seen)}</time>
              </div>
            </article>
          ))
        )}
      </section>

      <section className="timeline-section">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Активность</p>
            <h2>Таймлайн дня</h2>
          </div>
          <label className="date-control">
            <select value={timelineMode} onChange={(event) => setTimelineMode(event.target.value as "day" | "week")}><option value="day">День</option><option value="week">Неделя</option></select>
            <span>Дата</span>
            <input type="date" value={selectedDate} onChange={(event) => setSelectedDate(event.target.value)} />
          </label>
        </div>

        <div className="timeline-card">
          <div className="time-axis" aria-hidden="true">
            {timelineMode === "day" ? <><span>00:00</span><span>06:00</span><span>12:00</span><span>18:00</span><span>24:00</span></> : [0,1,2,3,4,5,6,7].map((day) => <span key={day}>{new Date(new Date(`${selectedDate}T00:00:00`).getTime() + day * 86400000).toLocaleDateString("ru-RU", { weekday: "short", day: "numeric" })}</span>)}
          </div>
          {timelineError ? (
            <div className="empty-state"><h2>Таймлайн недоступен</h2><p>{timelineError}</p></div>
          ) : !timeline || timeline.employees.length === 0 ? (
            <div className="empty-state"><h2>Активности пока нет</h2><p>Запустите эмулятор или Windows-агент.</p></div>
          ) : (
            <TeamTimelineCanvas timeline={timeline} onSelectEmployee={(id) => { setSelectedEmployeeId(id); setActiveView("employee"); }} onAction={timelineAction} />
          )}
        </div>

        <div className="timeline-legend">
          {(["PRODUCTIVE", "NEUTRAL", "UNPRODUCTIVE", "IDLE", "LOCKED", "BREAK"] as const).map((state) => (
            <span key={state}><i className={`segment-${state.toLowerCase()}`} />{statusLabels[state]}</span>
          ))}
        </div>
      </section>
      </>}
    </main>
  );
}

export function App() {
  const [user, setUser] = useState<UserInfo | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const restore = async () => {
      try {
        let response = await fetch("/api/v1/auth/me");
        if (!response.ok) {
          response = await fetch("/api/v1/auth/refresh", { method: "POST" });
        }
        if (response.ok) {
          const body = await response.json();
          if (!cancelled) setUser(body.user ?? body);
        }
      } finally {
        if (!cancelled) setCheckingSession(false);
      }
    };
    void restore();
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!user) return;
    const refreshSession = async () => {
      const response = await fetch("/api/v1/auth/refresh", { method: "POST" });
      if (!response.ok) {
        setUser(null);
        return;
      }
      const body = await response.json();
      setUser(body.user);
    };
    const timer = window.setInterval(() => void refreshSession(), 12 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, [user?.id]);

  const logout = async () => {
    try {
      await fetch("/api/v1/auth/logout", { method: "POST" });
    } finally {
      setUser(null);
    }
  };

  if (checkingSession) {
    return <main className="session-loader"><span /><p>Проверяем защищённую сессию…</p></main>;
  }
  if (!user) return <LoginScreen onAuthenticated={setUser} />;
  return <AuthenticatedApp user={user} onLogout={() => void logout()} />;
}
