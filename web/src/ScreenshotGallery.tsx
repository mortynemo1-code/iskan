import { useEffect, useMemo, useState } from "react";

type Screenshot = {
  id: number;
  employee_name: string | null;
  hostname: string;
  taken_at: string;
  width: number;
  height: number;
  size_bytes: number;
  is_blurred: boolean;
  duplicate_of_id: number | null;
  state: string | null;
  category_name: string | null;
  app_name: string | null;
  url_domain: string | null;
  thumbnail_url: string;
  image_url: string;
};

function localDate(date: Date) {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

export function ScreenshotGallery({ employeeId, canExport }: { employeeId: string; canExport: boolean }) {
  const now = new Date();
  const weekAgo = new Date(now);
  weekAgo.setDate(weekAgo.getDate() - 7);
  const [from, setFrom] = useState(localDate(weekAgo));
  const [to, setTo] = useState(localDate(now));
  const [state, setState] = useState("");
  const [view, setView] = useState<"grid" | "timeline">("grid");
  const [items, setItems] = useState<Screenshot[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const range = useMemo(() => {
    const start = new Date(`${from}T00:00:00`);
    const end = new Date(`${to}T00:00:00`);
    end.setDate(end.getDate() + 1);
    return { start, end };
  }, [from, to]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      try {
        const params = new URLSearchParams({ employee_id: employeeId, from: range.start.toISOString(), to: range.end.toISOString(), limit: "200" });
        if (state) params.set("state", state);
        const response = await fetch(`/api/v1/screenshots?${params}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        if (!cancelled) { setItems(body.items); setError(null); }
      } catch (loadError) {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : "Ошибка загрузки");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    return () => { cancelled = true; };
  }, [employeeId, range, state]);

  const selectedIndex = items.findIndex((item) => item.id === selectedId);
  const selected = selectedIndex >= 0 ? items[selectedIndex] : null;
  useEffect(() => {
    if (!selected) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSelectedId(null);
      if (event.key === "ArrowLeft" && selectedIndex > 0) setSelectedId(items[selectedIndex - 1].id);
      if (event.key === "ArrowRight" && selectedIndex < items.length - 1) setSelectedId(items[selectedIndex + 1].id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [items, selected, selectedIndex]);

  const exportParams = new URLSearchParams({ employee_id: employeeId, from: range.start.toISOString(), to: range.end.toISOString() });

  return (
    <section className="screenshot-gallery">
      <div className="gallery-toolbar">
        <label><span>С</span><input type="date" value={from} onChange={(event) => setFrom(event.target.value)} /></label>
        <label><span>По</span><input type="date" value={to} onChange={(event) => setTo(event.target.value)} /></label>
        <label><span>Состояние</span><select value={state} onChange={(event) => setState(event.target.value)}><option value="">Все</option><option value="PRODUCTIVE">Работа</option><option value="NEUTRAL">Нейтрально</option><option value="UNPRODUCTIVE">Непродуктивно</option><option value="IDLE">Простой</option></select></label>
        <div className="view-switch"><button className={view === "grid" ? "active" : ""} onClick={() => setView("grid")}>Сетка</button><button className={view === "timeline" ? "active" : ""} onClick={() => setView("timeline")}>Лента</button></div>
        {canExport && <a className="export-button" href={`/api/v1/screenshots/export.zip?${exportParams}`}>Скачать ZIP</a>}
      </div>
      {error ? <div className="notice notice-error">Галерея недоступна: {error}</div> : loading ? <div className="dashboard-loading">Загружаем миниатюры…</div> : items.length === 0 ? <div className="dashboard-card media-coming"><strong>Скриншотов за период нет</strong><p>Они появятся после первой съёмки агентом.</p></div> : (
        <div className={`screenshots-${view}`}>{items.map((item) => <article className="screenshot-card" key={item.id} onClick={() => setSelectedId(item.id)}>
          <div className="screenshot-image-wrap"><img src={item.thumbnail_url} loading="lazy" alt={`Скриншот ${new Date(item.taken_at).toLocaleString("ru-RU")}`} />{item.is_blurred && <span className="blur-badge">Размыто</span>}{item.duplicate_of_id && <span className="duplicate-badge">Дубликат</span>}</div>
          <div className="screenshot-meta"><time>{new Date(item.taken_at).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" })}</time><strong>{item.app_name ?? item.url_domain ?? item.hostname}</strong><span>{[item.category_name, item.state].filter(Boolean).join(" · ")}</span></div>
        </article>)}</div>
      )}
      {selected && <div className="lightbox" role="dialog" aria-modal="true" aria-label="Просмотр скриншота" onClick={() => setSelectedId(null)}>
        <button className="lightbox-close" aria-label="Закрыть" onClick={() => setSelectedId(null)}>×</button>
        <button className="lightbox-nav previous" disabled={selectedIndex <= 0} onClick={(event) => { event.stopPropagation(); setSelectedId(items[selectedIndex - 1]?.id ?? selected.id); }}>‹</button>
        <div className="lightbox-content" onClick={(event) => event.stopPropagation()}>
          <img src={selected.image_url} alt="Полный скриншот" />
          <div><span><strong>{new Date(selected.taken_at).toLocaleString("ru-RU")}</strong><small>{selected.width}×{selected.height} · {selected.hostname}</small></span><span>{[selected.app_name, selected.url_domain, selected.category_name, selected.state].filter(Boolean).join(" · ")}</span>{canExport && <a href={`${selected.image_url}?download=true`}>Скачать файл</a>}</div>
        </div>
        <button className="lightbox-nav next" disabled={selectedIndex >= items.length - 1} onClick={(event) => { event.stopPropagation(); setSelectedId(items[selectedIndex + 1]?.id ?? selected.id); }}>›</button>
      </div>}
    </section>
  );
}
