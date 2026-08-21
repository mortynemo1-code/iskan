import { FormEvent, useCallback, useEffect, useState } from "react";

type Device = { id: string; hostname: string; employee_name: string | null; agent_version: string; is_approved: boolean; last_seen: string | null };
type Release = { id: string; version: string; sha256: string; rollout_percent: number; is_active: boolean; created_at: string };
type Diagnostic = { id: string; hostname: string; size_bytes: number; reason: string | null; created_at: string; download_url: string };

export function AgentOperationsAdmin() {
  const [devices, setDevices] = useState<Device[]>([]); const [releases, setReleases] = useState<Release[]>([]); const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([]);
  const [message, setMessage] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    const [deviceResponse, releaseResponse, diagnosticResponse] = await Promise.all([fetch("/api/v1/admin/devices"), fetch("/api/v1/admin/update-releases"), fetch("/api/v1/admin/diagnostics")]);
    if (deviceResponse.ok) setDevices(await deviceResponse.json()); if (releaseResponse.ok) setReleases(await releaseResponse.json()); if (diagnosticResponse.ok) setDiagnostics(await diagnosticResponse.json());
  }, []);
  useEffect(() => { void load(); }, [load]);
  const command = async (device: Device, value: string) => {
    setBusy(true); const response = await fetch(`/api/v1/admin/devices/${device.id}/commands`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ command: value }) });
    setMessage(response.ok ? `${device.hostname}: команда поставлена в очередь` : `Ошибка команды: HTTP ${response.status}`); setBusy(false);
  };
  const upload = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); setBusy(true); const form = event.currentTarget; const body = new FormData(form);
    const response = await fetch("/api/v1/admin/update-releases", { method: "POST", body });
    setMessage(response.ok ? "MSI загружен; включите релиз после проверки подписи" : `MSI не загружен: HTTP ${response.status}`); if (response.ok) { form.reset(); await load(); } setBusy(false);
  };
  const patchRelease = async (release: Release, changes: Partial<Release>) => {
    const response = await fetch(`/api/v1/admin/update-releases/${release.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(changes) });
    setMessage(response.ok ? "Параметры раскатки обновлены" : `Ошибка: HTTP ${response.status}`); if (response.ok) await load();
  };
  return <section className="admin-section"><div className="section-heading compact"><div><p className="eyebrow">Эксплуатация</p><h2>Агенты, обновления и диагностика</h2></div></div>{message && <div className="notice">{message}</div>}<div className="agent-ops-grid">
    <article className="admin-card agent-ops"><div className="card-heading"><span>Команды устройствам</span><small>{devices.filter((item) => item.is_approved).length} подтверждено</small></div>{devices.filter((item) => item.is_approved).map((device) => <div className="agent-op-row" key={device.id}><span><strong>{device.hostname}</strong><small>{device.employee_name ?? "Не назначен"} · v{device.agent_version}</small></span><button disabled={busy} onClick={() => void command(device, "send_logs")}>Логи</button><button disabled={busy} onClick={() => void command(device, "update_agent")}>Обновить</button><button disabled={busy} onClick={() => void command(device, "restart_agent")}>Перезапустить</button></div>)}</article>
    <article className="admin-card agent-ops"><div className="card-heading"><span>Канареечные обновления</span><small>только подписанные MSI</small></div><form className="release-form" onSubmit={upload}><input name="version" required pattern="\d+\.\d+\.\d+.*" placeholder="1.1.0" /><input name="rollout_percent" type="number" min="0" max="100" defaultValue="5" /><input name="package" type="file" accept=".msi" required /><button disabled={busy}>Загрузить MSI</button></form>{releases.map((release) => <div className="release-row" key={release.id}><span><strong>v{release.version}</strong><small>{release.sha256.slice(0, 12)}… · {new Date(release.created_at).toLocaleString("ru-RU")}</small></span><label><input type="number" min="0" max="100" defaultValue={release.rollout_percent} onBlur={(event) => void patchRelease(release, { rollout_percent: Number(event.target.value) })} />%</label><button className={release.is_active ? "active" : ""} onClick={() => void patchRelease(release, { is_active: !release.is_active })}>{release.is_active ? "Активен" : "Включить"}</button></div>)}</article>
  </div><article className="admin-card agent-ops diagnostics"><div className="card-heading"><span>Диагностические архивы</span><small>последние 200</small></div>{diagnostics.length === 0 ? <p className="admin-empty">Архивов пока нет.</p> : diagnostics.map((item) => <a className="diagnostic-row" href={item.download_url} key={item.id}><strong>{item.hostname}</strong><span>{item.reason ?? "по команде"}</span><span>{(item.size_bytes / 1024).toFixed(0)} КБ</span><time>{new Date(item.created_at).toLocaleString("ru-RU")}</time></a>)}</article></section>;
}
