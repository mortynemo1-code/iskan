import { FormEvent, useCallback, useEffect, useState } from "react";

type ColorScheme = { id: string; name: string; colors: Record<string, string>; patterns_enabled: boolean; is_default: boolean };
type ThresholdScheme = { id: string; name: string; rules: Array<{ min: number; code: string; label: string; color: string }>; is_default: boolean };
type Appearance = { color_scheme_id: string; threshold_scheme_id: string };
type Retention = { id: string; data_type: string; scope_type: string; scope_id: string | null; days: number };
type AgentSetting = { value: Record<string, unknown> };
type AuditItem = { id: number; user_name: string | null; action: string; object_type: string; object_id: string | null; target_employee_name: string | null; ip_address: string | null; created_at: string; details: Record<string, unknown> };
type AuditPage = { items: AuditItem[]; total: number };

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init, headers: init?.body ? { "Content-Type": "application/json", ...init.headers } : init?.headers });
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail ?? `HTTP ${response.status}`); }
  return response.status === 204 ? undefined as T : response.json();
}

const states = ["PRODUCTIVE", "NEUTRAL", "UNPRODUCTIVE", "IDLE", "LOCKED", "BREAK", "ABSENCE", "OFFLINE"];

export function SystemSettings() {
  const [colors, setColors] = useState<ColorScheme[]>([]); const [thresholds, setThresholds] = useState<ThresholdScheme[]>([]);
  const [appearance, setAppearance] = useState<Appearance | null>(null); const [retention, setRetention] = useState<Retention[]>([]);
  const [agent, setAgent] = useState<Record<string, unknown>>({}); const [audit, setAudit] = useState<AuditItem[]>([]);
  const [auditAction, setAuditAction] = useState(""); const [message, setMessage] = useState<string | null>(null);
  const [capacity, setCapacity] = useState({ employees: 100, bitrate: 500, days: 7 });

  const load = useCallback(async () => {
    try {
      const [colorRows, thresholdRows, active, retentionRows, agentRows, auditPage] = await Promise.all([
        api<ColorScheme[]>("/api/v1/color-schemes"), api<ThresholdScheme[]>("/api/v1/threshold-schemes"),
        api<Appearance>("/api/v1/settings/appearance"), api<Retention[]>("/api/v1/settings/retention"),
        api<AgentSetting[]>("/api/v1/settings/agent"), api<AuditPage>(`/api/v1/audit-log?per_page=100${auditAction ? `&action=${encodeURIComponent(auditAction)}` : ""}`),
      ]);
      setColors(colorRows); setThresholds(thresholdRows); setAppearance(active); setRetention(retentionRows); setAgent(agentRows[0]?.value ?? {}); setAudit(auditPage.items);
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Ошибка настроек"); }
  }, [auditAction]);
  useEffect(() => { void load(); }, [load]);

  const saveAppearance = async (colorSchemeId: string, thresholdSchemeId: string) => {
    const result = await api<Appearance>("/api/v1/settings/appearance", { method: "PUT", body: JSON.stringify({ color_scheme_id: colorSchemeId, threshold_scheme_id: thresholdSchemeId }) });
    setAppearance(result); setMessage("Оформление применено"); window.dispatchEvent(new Event("appearance-changed"));
  };
  const saveAgent = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const values = new FormData(event.currentTarget); const value = {
      idle_threshold_sec: Number(values.get("idle")), screenshot_enabled: values.get("screenshots") === "on",
      screenshot_interval_sec: Number(values.get("screenshot_interval")), screenshot_all_monitors: values.get("all_monitors") === "on",
      screenshot_multi_monitor_mode: values.get("multi_monitor_mode"),
      screenshot_on_unproductive: values.get("on_unproductive") === "on", schedule_grace_minutes: Number(values.get("grace")),
      personal_time_enabled: values.get("personal_time") === "on", collect_window_titles: values.get("titles") === "on", collect_browser_urls: values.get("urls") === "on",
      treat_media_playback_as_activity: values.get("media_playback") === "on", collect_outside_schedule_activity: values.get("outside_schedule") === "on",
      video_recording_mode: values.get("video_mode"), video_profile: values.get("video_profile"),
      video_trigger_minutes: Number(values.get("video_trigger")), video_on_demand_timeout_minutes: Number(values.get("video_timeout")),
      video_schedule_windows: (() => { try { return JSON.parse(String(values.get("video_windows") ?? "[]")); } catch { return []; } })(),
      screenshot_blur_mode: values.get("blur_mode"), private_app_patterns: String(values.get("private_apps") ?? "").split(",").map((item) => item.trim()).filter(Boolean),
      privacy_contact: values.get("privacy_contact"), privacy_retention_notice: values.get("privacy_retention"),
    };
    void api("/api/v1/settings/agent", { method: "PUT", body: JSON.stringify({ scope_type: "global", scope_id: null, value }) }).then(() => { setMessage("Параметры агента сохранены"); void load(); }).catch((reason) => setMessage(reason.message));
  };
  const saveRetention = async (item: Retention, days: number) => {
    await api("/api/v1/settings/retention", { method: "PUT", body: JSON.stringify({ data_type: item.data_type, scope_type: item.scope_type, scope_id: item.scope_id, days }) }); setMessage("Ретеншен обновлён"); await load();
  };

  return <section className="admin-section system-settings">
    <div className="section-heading compact"><div><p className="eyebrow">Политики системы</p><h2>Сбор, оформление, хранение и аудит</h2></div></div>
    {message && <div className="notice">{message}</div>}
    <div className="settings-grid">
      <article className="admin-card"><div className="card-heading"><span>Цветовая схема</span><small>таймлайн и диаграммы</small></div><div className="scheme-list">{colors.map((scheme) => <button className={appearance?.color_scheme_id === scheme.id ? "active" : ""} key={scheme.id} onClick={() => appearance && void saveAppearance(scheme.id, appearance.threshold_scheme_id)}><strong>{scheme.name}</strong><span>{states.map((state) => <i key={state} style={{ background: scheme.colors[state] }} title={state} />)}</span><small>{scheme.patterns_enabled ? "Цвет + паттерны" : "Только цвет"}</small></button>)}</div></article>
      <article className="admin-card"><div className="card-heading"><span>Пороговая схема</span><small>оценка процентов</small></div><div className="threshold-list">{thresholds.map((scheme) => <button className={appearance?.threshold_scheme_id === scheme.id ? "active" : ""} key={scheme.id} onClick={() => appearance && void saveAppearance(appearance.color_scheme_id, scheme.id)}><strong>{scheme.name}</strong><span>{scheme.rules.sort((a,b) => b.min-a.min).map((rule) => <i key={rule.code} style={{ background: rule.color, width: `${Math.max(12, 100 / scheme.rules.length)}%` }}>{rule.min}+ · {rule.label}</i>)}</span></button>)}</div></article>
      <article className="admin-card agent-settings-card"><div className="card-heading"><span>Параметры сбора</span><small>глобальный профиль</small></div><form key={JSON.stringify(agent)} className="settings-form" onSubmit={saveAgent}><label><span>Idle-порог, сек</span><input name="idle" type="number" min="60" max="1800" defaultValue={Number(agent.idle_threshold_sec ?? 300)} /></label><label><span>Скриншот каждые, сек</span><input name="screenshot_interval" type="number" min="60" max="3600" defaultValue={Number(agent.screenshot_interval_sec ?? 300)} /></label><label><span>Несколько мониторов</span><select name="multi_monitor_mode" defaultValue={String(agent.screenshot_multi_monitor_mode ?? "merge")}><option value="merge">Склеить в один снимок</option><option value="separate">Отдельный файл на монитор</option></select></label><label><span>Режим видеозаписи</span><select name="video_mode" defaultValue={String(agent.video_recording_mode ?? "on_demand")}><option value="off">Выключено</option><option value="on_demand">По требованию</option><option value="always_on">Всю смену</option><option value="scheduled">По окнам</option><option value="trigger">По непродуктивной активности</option></select></label><label><span>Профиль видео</span><select name="video_profile" defaultValue={String(agent.video_profile ?? "medium")}><option value="low">Low · 720p/5 fps</option><option value="medium">Medium · 720p/10 fps</option><option value="high">High · 1080p/15 fps</option></select></label><label><span>Триггер, минут</span><input name="video_trigger" type="number" min="1" max="240" defaultValue={Number(agent.video_trigger_minutes ?? 5)} /></label><label><span>Автостоп просмотра, минут</span><input name="video_timeout" type="number" min="1" max="480" defaultValue={Number(agent.video_on_demand_timeout_minutes ?? 30)} /></label><label><span>Окна записи, JSON</span><input name="video_windows" defaultValue={JSON.stringify(agent.video_schedule_windows ?? [{ weekdays: [1,2,3,4,5], start: "09:00", end: "18:00" }])} /></label><label><span>Допуск к графику, мин</span><input name="grace" type="number" min="0" max="240" defaultValue={Number(agent.schedule_grace_minutes ?? 60)} /></label><label><span>Размытие снимков</span><select name="blur_mode" defaultValue={String(agent.screenshot_blur_mode ?? "none")}><option value="none">Выключено</option><option value="full">Весь экран</option><option value="private_apps">Только приватные приложения</option></select></label><label><span>Приватные маски, через запятую</span><input name="private_apps" defaultValue={Array.isArray(agent.private_app_patterns) ? agent.private_app_patterns.join(", ") : "keepass, bitwarden, bank"} /></label><label><span>Ответственный / контакт</span><input name="privacy_contact" defaultValue={String(agent.privacy_contact ?? "Ответственный назначается работодателем")} /></label><label><span>Текст о хранении</span><input name="privacy_retention" defaultValue={String(agent.privacy_retention_notice ?? "События 365 дней, скриншоты 30 дней, видео 7 дней")} /></label>{[["screenshots","Скриншоты",agent.screenshot_enabled],["all_monitors","Все мониторы",agent.screenshot_all_monitors],["on_unproductive","Снимок при непродуктивном",agent.screenshot_on_unproductive],["personal_time","Личное время",agent.personal_time_enabled],["titles","Заголовки окон",agent.collect_window_titles],["urls","URL браузеров",agent.collect_browser_urls],["media_playback","Медиаплеер считается активностью",agent.treat_media_playback_as_activity],["outside_schedule","Фиксировать факт работы вне графика",agent.collect_outside_schedule_activity]].map(([name,label,checked]) => <label className="settings-check" key={String(name)}><input name={String(name)} type="checkbox" defaultChecked={checked !== false} />{String(label)}</label>)}<button className="primary-button">Сохранить профиль</button></form></article>
      <article className="admin-card"><div className="card-heading"><span>Сроки хранения</span><small>автоудаление</small></div><div className="retention-list">{retention.filter((item) => item.scope_type === "global").map((item) => <label key={item.id}><span><strong>{{ screenshots: "Скриншоты", video: "Видео", events: "События" }[item.data_type] ?? item.data_type}</strong><small>Глобальная политика</small></span><input type="number" min="1" max={item.data_type === "video" ? 90 : 3650} defaultValue={item.days} onBlur={(event) => void saveRetention(item, Number(event.target.value))} /><em>дней</em></label>)}</div></article>
    </div>
    <article className="admin-card capacity-card"><div className="card-heading"><span>Калькулятор видеохранилища</span><small>8 часов в день × 22 рабочих дня</small></div><div className="capacity-inputs"><label><span>Сотрудников</span><input type="number" min="1" max="5000" value={capacity.employees} onChange={(event) => setCapacity({ ...capacity, employees: Number(event.target.value) })} /></label><label><span>Профиль</span><select value={capacity.bitrate} onChange={(event) => setCapacity({ ...capacity, bitrate: Number(event.target.value) })}><option value="250">Low · 250 kbps</option><option value="500">Medium · 500 kbps</option><option value="1200">High · 1200 kbps</option></select></label><label><span>Ретеншен, дней</span><input type="number" min="1" max="90" value={capacity.days} onChange={(event) => setCapacity({ ...capacity, days: Number(event.target.value) })} /></label><strong>{(capacity.employees * capacity.bitrate * 3600 * 8 * capacity.days / 8 / 1_000_000_000).toFixed(2)} ТБ</strong></div>{capacity.employees * capacity.bitrate * 3600 * 8 * capacity.days / 8 / 1_000_000_000 > 2 && <div className="notice notice-error">Расчёт превышает базовый диск 2 ТБ — увеличьте хранилище или снизьте профиль/ретеншен.</div>}</article>
    <article className="admin-card audit-card"><div className="card-heading"><span>Неизменяемый журнал аудита</span><label><small>Фильтр действия</small><input value={auditAction} onChange={(event) => setAuditAction(event.target.value)} placeholder="stream_viewed" /></label></div><div className="audit-table-wrap"><table><thead><tr><th>Время</th><th>Пользователь</th><th>Действие</th><th>Объект</th><th>Сотрудник</th><th>IP</th><th>Детали</th></tr></thead><tbody>{audit.map((item) => <tr key={item.id}><td>{new Date(item.created_at).toLocaleString("ru-RU")}</td><td>{item.user_name ?? "Система"}</td><td><code>{item.action}</code></td><td>{item.object_type} · {item.object_id}</td><td>{item.target_employee_name ?? "—"}</td><td>{item.ip_address ?? "—"}</td><td title={JSON.stringify(item.details)}>{JSON.stringify(item.details)}</td></tr>)}</tbody></table></div></article>
  </section>;
}
