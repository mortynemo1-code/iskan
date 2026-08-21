import { MouseEvent, WheelEvent, useEffect, useMemo, useRef, useState } from "react";

type Segment = { event_uuid: string; ts_start: string; ts_end: string; duration_sec: number; state: string; app_name: string | null; process_name: string | null; window_title: string | null; url_domain: string | null; url_path: string | null; category_id: number | null };
type Employee = { device_id: string; employee_id: string | null; employee_name: string | null; hostname: string; department_name: string | null; segments: Segment[]; totals: { productive: number } };
type Timeline = { range_start: string; range_end: string; employees: Employee[] };
type Hit = { x: number; y: number; width: number; height: number; employee: Employee; segment: Segment };
export type TimelineAction = "video" | "screenshots" | "violation" | "category";

const stateFallback: Record<string, string> = { PRODUCTIVE: "#2e7d32", NEUTRAL: "#78909c", UNPRODUCTIVE: "#f9a825", IDLE: "#c62828", LOCKED: "#8f2525", BREAK: "#0288d1" };
const labels: Record<string, string> = { PRODUCTIVE: "Работа", NEUTRAL: "Нейтрально", UNPRODUCTIVE: "Непродуктивно", IDLE: "Простой", LOCKED: "Заблокировано", BREAK: "Личное время" };
const rowHeight = 44; const labelWidth = 190;

export function TeamTimelineCanvas({ timeline, onSelectEmployee, onAction }: { timeline: Timeline; onSelectEmployee: (id: string) => void; onAction?: (action: TimelineAction, employee: Employee, segment: Segment) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null); const wrapper = useRef<HTMLDivElement>(null); const hits = useRef<Hit[]>([]);
  const [size, setSize] = useState(900); const [view, setView] = useState({ start: 0, end: 1 }); const [drag, setDrag] = useState<{ x: number; start: number; end: number } | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; employee: Employee; segment: Segment } | null>(null);
  const [menu, setMenu] = useState<{ x: number; y: number; employee: Employee; segment: Segment } | null>(null);
  const thumbnails = useRef(new Map<string, { thumbnail_url: string; category_name: string | null; taken_at: string }>());
  const [thumbnail, setThumbnail] = useState<{ thumbnail_url: string; category_name: string | null; taken_at: string } | null>(null);
  const fullStart = useMemo(() => new Date(timeline.range_start).getTime(), [timeline.range_start]);
  const fullEnd = useMemo(() => new Date(timeline.range_end).getTime(), [timeline.range_end]);
  useEffect(() => { setView({ start: 0, end: 1 }); }, [timeline.range_start, timeline.range_end]);
  useEffect(() => { if (!wrapper.current) return; const observer = new ResizeObserver(([entry]) => setSize(Math.max(600, entry.contentRect.width))); observer.observe(wrapper.current); return () => observer.disconnect(); }, []);
  useEffect(() => {
    setThumbnail(null); if (!tooltip?.employee.employee_id) return;
    const key = `${tooltip.employee.employee_id}:${tooltip.segment.event_uuid}`; const cached = thumbnails.current.get(key);
    if (cached) { setThumbnail(cached); return; }
    let cancelled = false; const timer = window.setTimeout(() => {
      const url = `/api/v1/screenshots/nearest?employee_id=${tooltip.employee.employee_id}&at=${encodeURIComponent(tooltip.segment.ts_start)}&max_distance_sec=3600`;
      void fetch(url).then(async (response) => { if (!response.ok) return; const body = await response.json(); thumbnails.current.set(key, body); if (!cancelled) setThumbnail(body); });
    }, 250);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [tooltip?.employee.employee_id, tooltip?.segment.event_uuid, tooltip?.segment.ts_start]);
  useEffect(() => {
    const element = canvas.current; if (!element) return; const ratio = window.devicePixelRatio || 1; const height = Math.max(rowHeight, timeline.employees.length * rowHeight);
    element.width = size * ratio; element.height = height * ratio; element.style.width = `${size}px`; element.style.height = `${height}px`;
    const context = element.getContext("2d"); if (!context) return; context.scale(ratio, ratio); context.clearRect(0, 0, size, height); context.font = "11px system-ui"; context.textBaseline = "middle";
    const trackWidth = size - labelWidth; const start = fullStart + (fullEnd - fullStart) * view.start; const end = fullStart + (fullEnd - fullStart) * view.end; const range = end - start;
    const styles = getComputedStyle(document.documentElement); hits.current = [];
    timeline.employees.forEach((employee, row) => {
      const y = row * rowHeight; context.fillStyle = row % 2 ? "#f6f8f5" : "#fbfcfa"; context.fillRect(0, y, size, rowHeight);
      context.strokeStyle = "#e2e8e2"; context.beginPath(); context.moveTo(0, y + rowHeight - .5); context.lineTo(size, y + rowHeight - .5); context.stroke();
      context.fillStyle = "#25362b"; context.font = "600 11px system-ui"; context.fillText((employee.employee_name ?? employee.hostname).slice(0, 25), 12, y + 15);
      context.fillStyle = "#7a867d"; context.font = "9px system-ui"; context.fillText(`${employee.department_name ?? employee.hostname} · ${(employee.totals.productive / 3600).toFixed(1)} ч`, 12, y + 30);
      context.save(); context.beginPath(); context.rect(labelWidth, y, trackWidth, rowHeight); context.clip();
      for (let hour = Math.ceil(start / 3_600_000) * 3_600_000; hour < end; hour += 3_600_000) { const x = labelWidth + (hour - start) / range * trackWidth; context.strokeStyle = new Date(hour).getHours() % 6 === 0 ? "#cfd8d0" : "#e8ece8"; context.beginPath(); context.moveTo(x, y); context.lineTo(x, y + rowHeight); context.stroke(); }
      employee.segments.forEach((segment) => {
        const segmentStart = Math.max(start, new Date(segment.ts_start).getTime()); const segmentEnd = Math.min(end, new Date(segment.ts_end).getTime()); if (segmentEnd <= segmentStart) return;
        const x = labelWidth + (segmentStart - start) / range * trackWidth; const width = Math.max(1, (segmentEnd - segmentStart) / range * trackWidth);
        const css = styles.getPropertyValue(`--state-${segment.state.toLowerCase()}`).trim(); context.fillStyle = css || stateFallback[segment.state] || "#78909c"; context.fillRect(x, y + 8, width, rowHeight - 16);
        hits.current.push({ x, y: y + 8, width, height: rowHeight - 16, employee, segment });
      }); context.restore();
    });
  }, [timeline, size, view, fullStart, fullEnd]);
  const point = (event: MouseEvent<HTMLCanvasElement>) => { const rect = event.currentTarget.getBoundingClientRect(); return { x: event.clientX - rect.left, y: event.clientY - rect.top }; };
  const move = (event: MouseEvent<HTMLCanvasElement>) => {
    const current = point(event); if (drag) { const trackWidth = size - labelWidth; const delta = (current.x - drag.x) / trackWidth * (drag.end - drag.start); const span = drag.end - drag.start; const start = Math.max(0, Math.min(1 - span, drag.start - delta)); setView({ start, end: start + span }); return; }
    const hit = hits.current.find((item) => current.x >= item.x && current.x <= item.x + item.width && current.y >= item.y && current.y <= item.y + item.height); setTooltip(hit ? { x: current.x, y: current.y, employee: hit.employee, segment: hit.segment } : null);
  };
  const wheel = (event: WheelEvent<HTMLCanvasElement>) => { event.preventDefault(); const x = Math.max(0, Math.min(1, (event.nativeEvent.offsetX - labelWidth) / (size - labelWidth))); const span = view.end - view.start; const nextSpan = Math.max(1 / 24, Math.min(1, span * (event.deltaY > 0 ? 1.22 : .82))); const anchor = view.start + span * x; let start = anchor - nextSpan * x; start = Math.max(0, Math.min(1 - nextSpan, start)); setView({ start, end: start + nextSpan }); };
  const click = (event: MouseEvent<HTMLCanvasElement>) => { const current = point(event); if (current.x < labelWidth) { const employee = timeline.employees[Math.floor(current.y / rowHeight)]; if (employee?.employee_id) onSelectEmployee(employee.employee_id); } };
  return <div className="canvas-timeline" ref={wrapper}><canvas ref={canvas} onWheel={wheel} onMouseDown={(event) => { const current = point(event); setMenu(null); setDrag({ x: current.x, ...view }); }} onMouseUp={() => setDrag(null)} onMouseLeave={() => { setDrag(null); setTooltip(null); }} onMouseMove={move} onClick={click} onContextMenu={(event) => { event.preventDefault(); const current = point(event); const hit = hits.current.find((item) => current.x >= item.x && current.x <= item.x + item.width && current.y >= item.y && current.y <= item.y + item.height); setMenu(hit ? { x: current.x, y: current.y, employee: hit.employee, segment: hit.segment } : null); }} />{tooltip && <div className="canvas-tooltip" style={{ left: Math.min(size - 300, tooltip.x + 12), top: tooltip.y + 12 }}><strong>{tooltip.employee.employee_name ?? tooltip.employee.hostname}</strong><span>{new Date(tooltip.segment.ts_start).toLocaleTimeString("ru-RU")}–{new Date(tooltip.segment.ts_end).toLocaleTimeString("ru-RU")} · {Math.round(tooltip.segment.duration_sec / 60)} мин</span><em>{labels[tooltip.segment.state] ?? tooltip.segment.state}{thumbnail?.category_name ? ` · ${thumbnail.category_name}` : tooltip.segment.category_id ? ` · категория #${tooltip.segment.category_id}` : ""}</em>{thumbnail && <img src={thumbnail.thumbnail_url} loading="lazy" alt="Ближайший снимок экрана" />}<small>{[tooltip.segment.app_name ?? tooltip.segment.process_name, tooltip.segment.window_title, tooltip.segment.url_domain, tooltip.segment.url_path].filter(Boolean).join(" · ")}</small></div>}{menu && <div className="timeline-context-menu" style={{ left: Math.min(size - 250, menu.x), top: menu.y }} role="menu">{[["video","Открыть запись на этот момент"],["screenshots","Показать скриншоты"],["violation","Отметить нарушение"],["category","Изменить категорию приложения"]].map(([action,label]) => <button key={action} onClick={() => { onAction?.(action as TimelineAction, menu.employee, menu.segment); setMenu(null); }}>{label}</button>)}</div>}</div>;
}
