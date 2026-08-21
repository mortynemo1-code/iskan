import { useCallback, useEffect, useState } from "react";

type PresenceItem = {
  employee_id: string | null; employee_name: string | null; department_name: string | null;
  hostname: string; is_online: boolean; status: string; is_approved: boolean;
};

type StreamItem = {
  id: string; employee_id: string | null; employee_name: string | null; department_name: string | null;
  hostname: string; started_at: string; profile: string; status: string; viewer_url: string;
};

async function problem(response: Response): Promise<string> {
  try { const body = await response.json(); return body.detail ?? `HTTP ${response.status}`; }
  catch { return `HTTP ${response.status}`; }
}

export function LiveWall() {
  const [streams, setStreams] = useState<StreamItem[]>([]);
  const [employees, setEmployees] = useState<PresenceItem[]>([]);
  const [profile, setProfile] = useState("medium");
  const [selected, setSelected] = useState<string>("");
  const [focused, setFocused] = useState<StreamItem | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [wallResponse, presenceResponse] = await Promise.all([fetch("/api/v1/stream/wall"), fetch("/api/v1/presence")]);
    if (wallResponse.ok) setStreams(await wallResponse.json());
    if (presenceResponse.ok) {
      const presence: PresenceItem[] = await presenceResponse.json();
      setEmployees(presence.filter((item) => item.employee_id && item.is_online && item.is_approved));
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(load, 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  const start = async () => {
    if (!selected) return;
    setBusy(true); setMessage(null);
    const response = await fetch(`/api/v1/stream/request/${selected}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile, mode: "on_demand" }),
    });
    setBusy(false);
    if (!response.ok) { setMessage(await problem(response)); return; }
    setMessage("Команда отправлена агенту. Поток появится через несколько секунд.");
    await load();
  };

  const stop = async (stream: StreamItem) => {
    if (!stream.employee_id) return;
    const response = await fetch(`/api/v1/stream/stop/${stream.employee_id}`, { method: "POST" });
    if (!response.ok) setMessage(await problem(response));
    else { setFocused(null); setMessage("Трансляция остановлена"); await load(); }
  };

  return <section className="live-page">
    <header className="dashboard-heading">
      <div><p className="eyebrow">Видеоконтроль</p><h1>Live-стена</h1><p>До 16 рабочих экранов одновременно, без звука</p></div>
      <div className="live-request">
        <select value={selected} onChange={(event) => setSelected(event.target.value)} aria-label="Сотрудник">
          <option value="">Выберите сотрудника онлайн</option>
          {employees.map((item) => <option key={item.employee_id!} value={item.employee_id!}>{item.employee_name ?? item.hostname} · {item.status}</option>)}
        </select>
        <select value={profile} onChange={(event) => setProfile(event.target.value)} aria-label="Качество">
        <option value="low">Низкое · 720p/250 kbps</option><option value="medium">Среднее · 720p/500 kbps</option><option value="high">Высокое · 1080p/1200 kbps</option>
        </select>
        <button className="primary-button" disabled={!selected || busy} onClick={() => void start()}>{busy ? "Запрос…" : "Начать трансляцию"}</button>
      </div>
    </header>
    {message && <div className="notice">{message}</div>}
    {streams.length === 0 ? <div className="empty-state live-empty"><h2>Активных трансляций нет</h2><p>Выберите сотрудника, который сейчас онлайн, и запустите просмотр.</p></div> :
      <div className="live-grid">{streams.map((stream) => <article className="live-tile" key={stream.id}>
        <button className="live-preview" onClick={() => setFocused(stream)} aria-label={`Открыть ${stream.employee_name}`}>
          <iframe src={`${stream.viewer_url}?controls=false&muted=true&autoplay=true`} title={`Экран ${stream.employee_name}`} allow="autoplay; fullscreen" />
          <span className="live-shield" />
        </button>
        <div><span><strong>{stream.employee_name ?? stream.hostname}</strong><small>{stream.department_name ?? stream.hostname}</small></span><em><i /> {stream.status === "live" ? "В эфире" : "Запуск"}</em></div>
      </article>)}</div>}
    {focused && <div className="live-modal" role="dialog" aria-modal="true">
      <button className="lightbox-close" onClick={() => setFocused(null)}>×</button>
      <div className="live-modal-content"><iframe src={`${focused.viewer_url}?controls=true&muted=true&autoplay=true`} title={`Экран ${focused.employee_name}`} allow="autoplay; fullscreen" /><footer><span><strong>{focused.employee_name}</strong><small>Трансляция начата {new Date(focused.started_at).toLocaleString("ru-RU")}</small></span><button onClick={() => void stop(focused)}>Остановить</button></footer></div>
    </div>}
  </section>;
}
