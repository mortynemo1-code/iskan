import { useEffect, useState } from "react";

type Notification = { id: number; notification_type: string; payload: Record<string, unknown>; is_read: boolean; created_at: string };
const labels: Record<string, string> = { absence_pending: "Новая заявка на отсутствие", absence_approved: "Заявка одобрена", absence_rejected: "Заявка отклонена", discipline_auto_event: "Обнаружено нарушение дисциплины", storage_pressure: "Критическое заполнение видеохранилища" };

function socketUrl(): string { return `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}/api/v1/ws/notifications`; }

export function NotificationBell() {
  const [items, setItems] = useState<Notification[]>([]); const [open, setOpen] = useState(false);
  useEffect(() => { const socket = new WebSocket(socketUrl()); socket.onmessage = (event) => setItems(JSON.parse(event.data)); return () => socket.close(); }, []);
  const unread = items.filter((item) => !item.is_read).length;
  const read = async (item: Notification) => { if (!item.is_read) { await fetch(`/api/v1/notifications/${item.id}/read`, { method: "POST" }); setItems((current) => current.map((value) => value.id === item.id ? { ...value, is_read: true } : value)); } };
  return <div className="notification-bell"><button aria-label="Уведомления" onClick={() => setOpen(!open)}>◔{unread > 0 && <b>{unread > 99 ? "99+" : unread}</b>}</button>{open && <div className="notification-panel"><header><strong>Уведомления</strong><span>{unread} новых</span></header>{items.length === 0 ? <p>Новых событий нет</p> : items.map((item) => <button className={item.is_read ? "read" : ""} key={item.id} onClick={() => void read(item)}><i /><span><strong>{labels[item.notification_type] ?? item.notification_type}</strong><small>{new Date(item.created_at).toLocaleString("ru-RU")}</small></span></button>)}</div>}</div>;
}
