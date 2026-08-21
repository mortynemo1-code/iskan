import { useEffect, useMemo, useRef, useState } from "react";

type Span = { start: string; duration: number; url: string };
type PresenceItem = { employee_id: string | null; employee_name: string | null; hostname: string };
type Segment = { ts_start: string; ts_end: string; state: string };

function today(): string { const now = new Date(); now.setMinutes(now.getMinutes() - now.getTimezoneOffset()); return now.toISOString().slice(0, 10); }

export function VideoArchive({ employeeId: fixedEmployeeId }: { employeeId?: string }) {
  const query = new URLSearchParams(window.location.search);
  const initialAt = query.get("at");
  const [employeeId, setEmployeeId] = useState(fixedEmployeeId ?? query.get("employee") ?? "");
  const [employees, setEmployees] = useState<PresenceItem[]>([]);
  const [date, setDate] = useState(() => initialAt ? initialAt.slice(0, 10) : today());
  const [spans, setSpans] = useState<Span[]>([]);
  const [selected, setSelected] = useState<Span | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [rate, setRate] = useState(1); const [skipIdle, setSkipIdle] = useState(false);
  const [clipStart, setClipStart] = useState<string | null>(null); const [clipEnd, setClipEnd] = useState<string | null>(null);
  const video = useRef<HTMLVideoElement>(null);
  const range = useMemo(() => { const start = new Date(`${date}T00:00:00`); const end = new Date(start); end.setDate(end.getDate() + 1); return { start, end }; }, [date]);

  useEffect(() => {
    if (fixedEmployeeId) return;
    void fetch("/api/v1/presence").then(async (response) => { if (response.ok) setEmployees(await response.json()); });
  }, [fixedEmployeeId]);

  useEffect(() => {
    if (!employeeId) { setSpans([]); return; }
    let cancelled = false; setLoading(true);
    const url = `/api/v1/stream/archive/${employeeId}/index?from=${encodeURIComponent(range.start.toISOString())}&to=${encodeURIComponent(range.end.toISOString())}`;
    void fetch(url).then(async (response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body: Span[] = await response.json();
      if (!cancelled) {
        setSpans(body);
        const at = initialAt ? new Date(initialAt).getTime() : NaN;
        setSelected(body.find((span) => at >= new Date(span.start).getTime() && at < new Date(span.start).getTime() + span.duration * 1000) ?? body[0] ?? null);
        setError(null);
      }
    }).catch((reason) => { if (!cancelled) setError(reason instanceof Error ? reason.message : "Ошибка загрузки"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [employeeId, range]);

  useEffect(() => {
    if (!employeeId) return;
    const url = `/api/v1/timeline?from=${encodeURIComponent(range.start.toISOString())}&to=${encodeURIComponent(range.end.toISOString())}`;
    void fetch(url).then(async (response) => {
      if (!response.ok) return;
      const body = await response.json();
      setSegments(body.employees.filter((item: { employee_id: string }) => item.employee_id === employeeId).flatMap((item: { segments: Segment[] }) => item.segments));
    });
  }, [employeeId, range]);

  useEffect(() => { if (video.current) video.current.playbackRate = rate; }, [rate, selected]);

  const currentInstant = () => selected ? new Date(new Date(selected.start).getTime() + (video.current?.currentTime ?? 0) * 1000).toISOString() : null;
  const seek = (delta: number) => { if (video.current) video.current.currentTime = Math.max(0, Math.min(video.current.duration || selected?.duration || 0, video.current.currentTime + delta)); };
  const skipIdleNow = () => {
    if (!skipIdle || !video.current || !selected) return;
    const now = new Date(selected.start).getTime() + video.current.currentTime * 1000;
    const idle = segments.find((item) => ["IDLE", "LOCKED", "BREAK"].includes(item.state) && new Date(item.ts_start).getTime() <= now && new Date(item.ts_end).getTime() > now);
    if (idle) video.current.currentTime = Math.min(selected.duration, (new Date(idle.ts_end).getTime() - new Date(selected.start).getTime()) / 1000);
  };

  const createClip = async () => {
    if (!clipStart || !clipEnd || clipStart >= clipEnd) { setError("Сначала отметьте начало и конец фрагмента"); return; }
    const response = await fetch("/api/v1/stream/clip", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ employee_id: employeeId, start: clipStart, end: clipEnd }) });
    if (!response.ok) { setError(`Фрагмент не создан: HTTP ${response.status}`); return; }
    const body = await response.json(); const link = document.createElement("a"); link.href = body.url; link.download = "workforce-clip.mp4"; link.click();
  };

  const pin = async () => {
    if (!selected) return;
    const start = new Date(selected.start); const end = new Date(start.getTime() + selected.duration * 1000);
    const response = await fetch("/api/v1/stream/segments/pin", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ employee_id: employeeId, start: start.toISOString(), end: end.toISOString(), reason: "Закреплено из архива" }) });
    if (response.ok) setError("Интервал закреплён и не будет удалён по ретеншену");
  };

  return <section className="video-archive">
    <div className="archive-toolbar">
      {!fixedEmployeeId && <label><span>Сотрудник</span><select value={employeeId} onChange={(event) => setEmployeeId(event.target.value)}><option value="">Выберите сотрудника</option>{employees.filter((item) => item.employee_id).map((item) => <option key={item.employee_id!} value={item.employee_id!}>{item.employee_name ?? item.hostname}</option>)}</select></label>}
      <label><span>Дата</span><input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
      {selected && <><a className="export-button" href={selected.url} download>Скачать MP4</a><button className="secondary-button" onClick={() => void pin()}>Закрепить</button></>}
    </div>
    {error && <div className="notice">{error}</div>}
    {loading ? <div className="dashboard-loading">Ищем записи…</div> : !employeeId ? <div className="empty-state"><h2>Выберите сотрудника</h2></div> : spans.length === 0 ? <div className="empty-state"><h2>За этот день записей нет</h2><p>Архив создаётся автоматически во время трансляций.</p></div> : <div className="archive-layout">
      <div className="archive-player"><video ref={video} key={selected?.url} controls autoPlay muted src={selected?.url} onTimeUpdate={skipIdleNow} /><div className="archive-controls"><button onClick={() => seek(-30)}>−30 с</button><button onClick={() => seek(-5)}>−5 с</button><select value={rate} onChange={(event) => setRate(Number(event.target.value))}>{[0.5,1,2,4,8].map((value) => <option value={value} key={value}>{value}×</option>)}</select><button onClick={() => seek(5)}>+5 с</button><button onClick={() => seek(30)}>+30 с</button><label><input type="checkbox" checked={skipIdle} onChange={(event) => setSkipIdle(event.target.checked)} /> Пропускать простой</label><button onClick={() => setClipStart(currentInstant())}>Начало</button><button onClick={() => setClipEnd(currentInstant())}>Конец</button><button disabled={!clipStart || !clipEnd} onClick={() => void createClip()}>Скачать фрагмент</button></div><div className="archive-state-rail" title="Состояния активности за день">{segments.map((segment) => { const left = (new Date(segment.ts_start).getTime() - range.start.getTime()) / 864000; const width = (new Date(segment.ts_end).getTime() - new Date(segment.ts_start).getTime()) / 864000; return <i key={`${segment.ts_start}-${segment.state}`} className={`segment-${segment.state.toLowerCase()}`} style={{ left: `${left}%`, width: `${Math.max(.08, width)}%` }} title={`${new Date(segment.ts_start).toLocaleTimeString("ru-RU")} · ${segment.state}`} />; })}</div>{clipStart && <small>Фрагмент: {new Date(clipStart).toLocaleTimeString("ru-RU")} — {clipEnd ? new Date(clipEnd).toLocaleTimeString("ru-RU") : "…"}</small>}</div>
      <aside><strong>Доступные интервалы</strong>{spans.map((span) => <button className={selected?.url === span.url ? "active" : ""} key={`${span.start}-${span.duration}`} onClick={() => setSelected(span)}><time>{new Date(span.start).toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time><span>{Math.round(span.duration / 60)} мин</span></button>)}</aside>
    </div>}
  </section>;
}
