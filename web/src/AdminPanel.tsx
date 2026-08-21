import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { ScheduleAdmin } from "./ScheduleAdmin";
import { SystemSettings } from "./SystemSettings";
import { WindowsAccountsAdmin } from "./WindowsAccountsAdmin";
import { AgentOperationsAdmin } from "./AgentOperationsAdmin";

type Department = {
  id: string;
  name: string;
  parent_id: string | null;
  employee_count: number;
};

type Employee = {
  id: string;
  full_name: string;
  email: string | null;
  department_id: string | null;
  department_name: string | null;
  timezone: string;
  planned_daily_minutes: number;
  status: string;
  devices_count: number;
};

type Device = {
  id: string;
  employee_id: string | null;
  employee_name: string | null;
  hostname: string;
  os_version: string;
  agent_version: string;
  is_approved: boolean;
  last_seen: string | null;
  last_activity_state: string | null;
};

type Productivity = "PRODUCTIVE" | "NEUTRAL" | "UNPRODUCTIVE";

type Category = {
  id: number;
  code: string;
  name: string;
  productivity: Productivity;
  color: string;
  is_system: boolean;
  rules_count: number;
};

type Rule = {
  id: number;
  priority: number;
  match_field: string;
  match_type: string;
  pattern: string;
  category_id: number;
  category_name: string;
  productivity: Productivity;
  enabled: boolean;
};

type Role = {
  code: string;
  name: string;
  permissions: string[];
};

type AdminUser = {
  id: string;
  login: string;
  display_name: string;
  role_code: string;
  role_name: string;
  employee_id: string | null;
  employee_name: string | null;
  scope_type: string;
  is_active: boolean;
  totp_enabled: boolean;
  department_ids: string[];
  employee_ids: string[];
};

type AdminData = {
  departments: Department[];
  employees: Employee[];
  devices: Device[];
  categories: Category[];
  rules: Rule[];
  roles: Role[];
  users: AdminUser[];
};

const productivityLabels: Record<Productivity, string> = {
  PRODUCTIVE: "Продуктивно",
  NEUTRAL: "Нейтрально",
  UNPRODUCTIVE: "Непродуктивно",
};

const fieldLabels: Record<string, string> = {
  process_name: "Процесс",
  window_title: "Заголовок окна",
  url_domain: "Домен",
  url_full: "Полный URL",
  file_path: "Путь к файлу",
};

const matchLabels: Record<string, string> = {
  exact: "равен",
  contains: "содержит",
  wildcard: "по маске",
  regex: "регулярное выражение",
};

const permissionLabels: Record<string, string> = {
  "presence:view": "Онлайн",
  "timeline:view": "Таймлайн",
  "reports:view": "Отчёты",
  "screenshot:view": "Скриншоты",
  "screenshot:export": "Экспорт скриншотов",
  "stream:live": "Live-видео",
  "stream:archive": "Архив видео",
  "stream:download": "Скачивание видео",
  "absence:manage": "Отсутствия",
  "settings:manage": "Настройки",
  "users:manage": "Пользователи",
  "audit:view": "Аудит",
};

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json", ...init.headers } : init?.headers,
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : message;
    } catch {
      // The status code remains useful when an upstream proxy returns HTML.
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function AdminPanel({ currentRole }: { currentRole: string }) {
  const [data, setData] = useState<AdminData>({
    departments: [],
    employees: [],
    devices: [],
    categories: [],
    rules: [],
    roles: [],
    users: [],
  });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [deviceAssignments, setDeviceAssignments] = useState<Record<string, string>>({});
  const [ruleTest, setRuleTest] = useState<string | null>(null);
  const [reclassification, setReclassification] = useState<{ id: string; status: string; total_events?: number; processed_events?: number } | null>(null);

  const load = useCallback(async () => {
    try {
      const [departments, employees, devices, categories, rules, roles, users] = await Promise.all([
        api<Department[]>("/api/v1/admin/departments"),
        api<Employee[]>("/api/v1/admin/employees"),
        api<Device[]>("/api/v1/admin/devices"),
        api<Category[]>("/api/v1/admin/categories"),
        api<Rule[]>("/api/v1/admin/rules"),
        api<Role[]>("/api/v1/admin/roles"),
        api<AdminUser[]>("/api/v1/admin/users"),
      ]);
      setData({ departments, employees, devices, categories, rules, roles, users });
      setError(null);
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : "Не удалось загрузить данные");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!reclassification || ["completed", "failed"].includes(reclassification.status)) return;
    const timer = window.setInterval(() => void api<typeof reclassification>(`/api/v1/admin/rules/reclassify/${reclassification.id}`).then(setReclassification).catch(() => undefined), 1500);
    return () => window.clearInterval(timer);
  }, [reclassification]);

  const mutate = async (action: () => Promise<unknown>, successMessage: string): Promise<boolean> => {
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      await action();
      await load();
      setMessage(successMessage);
      return true;
    } catch (mutationError) {
      setError(mutationError instanceof Error ? mutationError.message : "Операция не выполнена");
      return false;
    } finally {
      setBusy(false);
    }
  };

  const pendingDevices = useMemo(
    () => data.devices.filter((device) => !device.is_approved),
    [data.devices],
  );
  const allPermissions = useMemo(
    () => Array.from(new Set(data.roles.flatMap((role) => role.permissions))).sort(),
    [data.roles],
  );

  const createDepartment = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    void mutate(
      () => api("/api/v1/admin/departments", {
        method: "POST",
        body: JSON.stringify({ name: formData.get("name") }),
      }),
      "Отдел добавлен",
    ).then((succeeded) => { if (succeeded) form.reset(); });
  };

  const createEmployee = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    void mutate(
      () => api("/api/v1/admin/employees", {
        method: "POST",
        body: JSON.stringify({
          full_name: formData.get("full_name"),
          email: formData.get("email") || null,
          department_id: formData.get("department_id") || null,
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
          planned_daily_minutes: Math.round(Number(formData.get("planned_hours") || 8) * 60),
        }),
      }),
      "Сотрудник добавлен",
    ).then((succeeded) => { if (succeeded) form.reset(); });
  };

  const approveDevice = (device: Device) => {
    const employeeId = deviceAssignments[device.id] ?? device.employee_id ?? "";
    if (!employeeId) {
      setError("Выберите сотрудника для устройства");
      return;
    }
    void mutate(
      () => api(`/api/v1/admin/devices/${device.id}`, {
        method: "PATCH",
        body: JSON.stringify({ employee_id: employeeId, is_approved: true }),
      }),
      `${device.hostname}: устройство подтверждено`,
    );
  };

  const createUser = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const scopeType = String(formData.get("scope_type"));
    const departmentId = String(formData.get("scope_department_id") ?? "");
    void mutate(
      () => api("/api/v1/admin/users", {
        method: "POST",
        body: JSON.stringify({
          login: formData.get("login"),
          display_name: formData.get("display_name"),
          password: formData.get("password"),
          role_code: formData.get("role_code"),
          employee_id: formData.get("employee_id") || null,
          scope_type: scopeType,
          department_ids: scopeType === "department" && departmentId ? [departmentId] : [],
          employee_ids: [],
        }),
      }),
      "Пользователь создан",
    ).then((succeeded) => { if (succeeded) form.reset(); });
  };

  const createCategory = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    void mutate(
      () => api("/api/v1/admin/categories", {
        method: "POST",
        body: JSON.stringify({
          code: formData.get("code"),
          name: formData.get("name"),
          productivity: formData.get("productivity"),
          color: formData.get("color"),
        }),
      }),
      "Категория добавлена",
    ).then((succeeded) => { if (succeeded) form.reset(); });
  };

  const createRule = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    void mutate(
      () => api("/api/v1/admin/rules", {
        method: "POST",
        body: JSON.stringify({
          priority: Number(formData.get("priority")),
          match_field: formData.get("match_field"),
          match_type: formData.get("match_type"),
          pattern: formData.get("pattern"),
          category_id: Number(formData.get("category_id")),
          enabled: true,
        }),
      }),
      "Правило добавлено",
    ).then((succeeded) => { if (succeeded) form.reset(); });
  };

  const testRule = async (form: HTMLFormElement) => {
    const formData = new FormData(form);
    try {
      const result = await api<{ events: number; duration_sec: number }>("/api/v1/admin/rules/test", {
        method: "POST",
        body: JSON.stringify({ match_field: formData.get("match_field"), match_type: formData.get("match_type"), pattern: formData.get("pattern"), days: 7 }),
      });
      setRuleTest(`За 7 дней: ${result.events} событий, ${(result.duration_sec / 3600).toFixed(1)} ч`);
    } catch (testError) { setError(testError instanceof Error ? testError.message : "Правило не проверено"); }
  };

  const startReclassification = async () => {
    try { setReclassification(await api("/api/v1/admin/rules/reclassify?days=30", { method: "POST" })); }
    catch (startError) { setError(startError instanceof Error ? startError.message : "Пересчёт не запущен"); }
  };

  return (
    <section className="admin-panel">
      <header className="topbar admin-heading">
        <div>
          <p className="eyebrow">Настройки системы</p>
          <h1>Администрирование</h1>
        </div>
        <div className="admin-stats">
          <span><strong>{pendingDevices.length}</strong> ждут подтверждения</span>
          <span><strong>{data.employees.length}</strong> сотрудников</span>
          <span><strong>{data.users.length}</strong> пользователей</span>
        </div>
      </header>

      {(error || message) && (
        <div className={`notice ${error ? "notice-error" : "notice-success"}`} role="status">
          {error ?? message}
        </div>
      )}

      <ScheduleAdmin />
      <SystemSettings />
      <WindowsAccountsAdmin />
      <AgentOperationsAdmin />

      <section className="admin-section">
        <div className="section-heading compact">
          <div><p className="eyebrow">Доступ и безопасность</p><h2>Пользователи и роли</h2></div>
        </div>
        <div className="admin-card access-card">
          <form className="user-form" onSubmit={createUser}>
            <label><span>Имя</span><input name="display_name" required placeholder="Иван Петров" /></label>
            <label><span>Логин</span><input name="login" required placeholder="i.petrov" /></label>
            <label><span>Временный пароль</span><input name="password" type="password" minLength={12} required placeholder="Не менее 12 символов" /></label>
            <label><span>Роль</span><select name="role_code" defaultValue="observer">{data.roles.map((role) => <option value={role.code} key={role.code}>{role.name}</option>)}</select></label>
            <label><span>Связанный сотрудник</span><select name="employee_id" defaultValue=""><option value="">Не связан</option>{data.employees.map((employee) => <option value={employee.id} key={employee.id}>{employee.full_name}</option>)}</select></label>
            <label><span>Область видимости</span><select name="scope_type" defaultValue="organization"><option value="organization">Вся организация</option><option value="department">Отдел</option><option value="employee">Только сотрудник</option></select></label>
            <label><span>Отдел для скоупа</span><select name="scope_department_id" defaultValue=""><option value="">Выберите</option>{data.departments.map((department) => <option value={department.id} key={department.id}>{department.name}</option>)}</select></label>
            <button className="button primary-button" disabled={busy || data.roles.length === 0}>Создать пользователя</button>
          </form>
          <div className="users-list">
            {data.users.map((adminUser) => (
              <article className={`user-row ${adminUser.is_active ? "" : "inactive-user"}`} key={adminUser.id}>
                <span className="avatar">{adminUser.display_name.slice(0, 1)}</span>
                <span className="user-identity"><strong>{adminUser.display_name}</strong><small>{adminUser.login}{adminUser.employee_name ? ` · ${adminUser.employee_name}` : ""}</small></span>
                <span className="role-badge">{adminUser.role_name}</span>
                <span className="scope-badge">{{ organization: "Вся организация", department: "Отделы", employee: "Сотрудники" }[adminUser.scope_type] ?? adminUser.scope_type}</span>
                {(["admin", "superadmin"].includes(adminUser.role_code)) && <span className={`two-fa ${adminUser.totp_enabled ? "enabled" : ""}`}>{adminUser.totp_enabled ? "2FA включена" : "2FA при входе"}</span>}
                <button
                  className={`toggle ${adminUser.is_active ? "on" : ""}`}
                  aria-label={adminUser.is_active ? "Отключить пользователя" : "Включить пользователя"}
                  disabled={busy}
                  onClick={() => void mutate(
                    () => api(`/api/v1/admin/users/${adminUser.id}`, { method: "PATCH", body: JSON.stringify({ is_active: !adminUser.is_active }) }),
                    adminUser.is_active ? "Пользователь отключён" : "Пользователь включён",
                  )}
                ><span /></button>
              </article>
            ))}
          </div>
          <div className="role-editor">
            <div className="role-editor-heading"><strong>Наборы прав</strong><span>Изменения применяются на сервере к следующему запросу пользователя.</span></div>
            {data.roles.map((role) => {
              const locked = role.code === "superadmin" && currentRole !== "superadmin";
              return (
                <article className="role-row" key={role.code}>
                  <div><strong>{role.name}</strong><small>{role.code}</small></div>
                  <div className="permission-grid">
                    {allPermissions.map((permission) => (
                      <label key={permission}>
                        <input
                          type="checkbox"
                          checked={role.permissions.includes(permission)}
                          disabled={busy || locked}
                          onChange={(event) => {
                            const permissions = event.target.checked
                              ? [...role.permissions, permission]
                              : role.permissions.filter((item) => item !== permission);
                            void mutate(
                              () => api(`/api/v1/admin/roles/${role.code}`, { method: "PATCH", body: JSON.stringify({ permissions }) }),
                              `Права роли «${role.name}» обновлены`,
                            );
                          }}
                        />
                        <span>{permissionLabels[permission] ?? permission}</span>
                      </label>
                    ))}
                  </div>
                </article>
              );
            })}
          </div>
        </div>
      </section>

      <section className="admin-section">
        <div className="section-heading compact">
          <div>
            <p className="eyebrow">Шаг 1</p>
            <h2>Новые устройства</h2>
          </div>
          <span className="section-count">{pendingDevices.length}</span>
        </div>
        <div className="admin-card device-queue">
          {loading ? (
            <p className="admin-empty">Загружаем устройства…</p>
          ) : pendingDevices.length === 0 ? (
            <p className="admin-empty">Новых устройств нет. После установки агента они появятся здесь.</p>
          ) : pendingDevices.map((device) => (
            <article className="device-row" key={device.id}>
              <div className="device-icon" aria-hidden="true">PC</div>
              <div className="device-copy">
                <strong>{device.hostname}</strong>
                <span>{device.os_version} · агент {device.agent_version}</span>
              </div>
              <label className="inline-field">
                <span>Сотрудник</span>
                <select
                  value={deviceAssignments[device.id] ?? device.employee_id ?? ""}
                  onChange={(event) => setDeviceAssignments((current) => ({
                    ...current,
                    [device.id]: event.target.value,
                  }))}
                >
                  <option value="">Выберите сотрудника</option>
                  {data.employees.filter((employee) => employee.status === "active").map((employee) => (
                    <option value={employee.id} key={employee.id}>{employee.full_name}</option>
                  ))}
                </select>
              </label>
              <button className="button primary-button" disabled={busy} onClick={() => approveDevice(device)}>
                Подтвердить
              </button>
            </article>
          ))}
        </div>
      </section>

      <section className="admin-grid admin-section">
        <div>
          <div className="section-heading compact">
            <div><p className="eyebrow">Команда</p><h2>Сотрудники</h2></div>
          </div>
          <div className="admin-card form-card">
            <form className="admin-form" onSubmit={createEmployee}>
              <label><span>ФИО</span><input name="full_name" required placeholder="Анна Смирнова" /></label>
              <label><span>Рабочая почта</span><input name="email" type="email" placeholder="a.smirnova@company.ru" /></label>
              <label>
                <span>Отдел</span>
                <select name="department_id" defaultValue="">
                  <option value="">Без отдела</option>
                  {data.departments.map((department) => (
                    <option value={department.id} key={department.id}>{department.name}</option>
                  ))}
                </select>
              </label>
              <label><span>План, часов/день</span><input name="planned_hours" type="number" min="0" max="24" step="0.5" defaultValue="8" required /></label>
              <button className="button primary-button" disabled={busy}>Добавить сотрудника</button>
            </form>
            <div className="compact-list">
              {data.employees.slice(0, 6).map((employee) => (
                <div className="compact-row" key={employee.id}>
                  <span className="avatar">{employee.full_name.slice(0, 1)}</span>
                  <span><strong>{employee.full_name}</strong><small>{employee.department_name ?? "Без отдела"}</small></span>
                  <small>{employee.devices_count} устр.</small>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div>
          <div className="section-heading compact">
            <div><p className="eyebrow">Структура</p><h2>Отделы</h2></div>
          </div>
          <div className="admin-card form-card">
            <form className="admin-form horizontal-form" onSubmit={createDepartment}>
              <label><span>Название отдела</span><input name="name" required placeholder="Разработка" /></label>
              <button className="button primary-button" disabled={busy}>Добавить</button>
            </form>
            <div className="compact-list departments-list">
              {data.departments.length === 0 ? (
                <p className="admin-empty small">Создайте первый отдел.</p>
              ) : data.departments.map((department) => (
                <div className="compact-row" key={department.id}>
                  <span className="department-mark" />
                  <strong>{department.name}</strong>
                  <small>{department.employee_count} чел.</small>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="admin-section">
        <div className="section-heading compact">
          <div><p className="eyebrow">Классификация</p><h2>Категории активности</h2></div>
        </div>
        <div className="admin-card rules-card">
          <form className="category-form" onSubmit={createCategory}>
            <label><span>Код</span><input name="code" required placeholder="messengers" pattern="[a-z][a-z0-9_-]{1,49}" /></label>
            <label><span>Название</span><input name="name" required placeholder="Мессенджеры" /></label>
            <label><span>Оценка</span><select name="productivity" defaultValue="NEUTRAL"><option value="PRODUCTIVE">Продуктивно</option><option value="NEUTRAL">Нейтрально</option><option value="UNPRODUCTIVE">Непродуктивно</option></select></label>
            <label className="color-field"><span>Цвет</span><input name="color" type="color" defaultValue="#78909c" /></label>
            <button className="button secondary-button" disabled={busy}>Добавить</button>
          </form>
          <div className="category-list">
            {data.categories.map((category) => (
              <article className="category-chip" key={category.id}>
                <i style={{ backgroundColor: category.color }} />
                <span><strong>{category.name}</strong><small>{category.code} · {category.rules_count} правил</small></span>
                <em className={`productivity ${category.productivity.toLowerCase()}`}>{productivityLabels[category.productivity]}</em>
                {!category.is_system && (
                  <button
                    className="icon-button"
                    title="Удалить категорию"
                    disabled={busy || category.rules_count > 0}
                    onClick={() => void mutate(
                      () => api(`/api/v1/admin/categories/${category.id}`, { method: "DELETE" }),
                      "Категория удалена",
                    )}
                  >×</button>
                )}
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="admin-section">
        <div className="section-heading compact">
          <div><p className="eyebrow">Приоритет: меньше — раньше</p><h2>Правила приложений и сайтов</h2></div>
          <button className="button secondary-button" disabled={busy || reclassification?.status === "running" || reclassification?.status === "queued"} onClick={() => void startReclassification()}>Пересчитать 30 дней</button>
        </div>
        {reclassification && <div className="notice">Пересчёт: {reclassification.status} · {reclassification.processed_events ?? 0} / {reclassification.total_events ?? 0}</div>}
        <div className="admin-card rules-card">
          <form className="rule-form" onSubmit={createRule}>
            <label><span>Приоритет</span><input name="priority" type="number" min="0" defaultValue="100" required /></label>
            <label><span>Поле</span><select name="match_field" defaultValue="url_domain"><option value="process_name">Процесс</option><option value="window_title">Заголовок окна</option><option value="url_domain">Домен</option><option value="url_full">Полный URL</option><option value="file_path">Путь к файлу</option></select></label>
            <label><span>Сравнение</span><select name="match_type" defaultValue="contains"><option value="exact">Равно</option><option value="contains">Содержит</option><option value="wildcard">Маска</option><option value="regex">Regex</option></select></label>
            <label className="pattern-field"><span>Шаблон</span><input name="pattern" required placeholder="youtube.com/shorts" /></label>
            <label><span>Категория</span><select name="category_id" required defaultValue=""><option value="" disabled>Выберите</option>{data.categories.map((category) => <option value={category.id} key={category.id}>{category.name}</option>)}</select></label>
            <button type="button" className="button secondary-button" disabled={busy} onClick={(event) => void testRule(event.currentTarget.form!)}>Тест 7 дней</button>
            <button className="button primary-button" disabled={busy || data.categories.length === 0}>Добавить правило</button>
          </form>
          {ruleTest && <div className="rule-test-result">{ruleTest}</div>}

          <div className="rules-table-wrap">
            <table className="rules-table">
              <thead><tr><th>Приоритет</th><th>Условие</th><th>Категория</th><th>Статус</th><th /></tr></thead>
              <tbody>
                {data.rules.map((rule) => (
                  <tr key={rule.id} className={rule.enabled ? "" : "disabled-rule"}>
                    <td><strong>{rule.priority}</strong></td>
                    <td><span className="condition">{fieldLabels[rule.match_field]} {matchLabels[rule.match_type]} <code>{rule.pattern}</code></span></td>
                    <td><span className={`productivity ${rule.productivity.toLowerCase()}`}>{rule.category_name}</span></td>
                    <td>
                      <button
                        className={`toggle ${rule.enabled ? "on" : ""}`}
                        aria-label={rule.enabled ? "Выключить правило" : "Включить правило"}
                        onClick={() => void mutate(
                          () => api(`/api/v1/admin/rules/${rule.id}`, { method: "PATCH", body: JSON.stringify({ enabled: !rule.enabled }) }),
                          rule.enabled ? "Правило выключено" : "Правило включено",
                        )}
                      ><span /></button>
                    </td>
                    <td><button className="icon-button" title="Удалить правило" onClick={() => void mutate(() => api(`/api/v1/admin/rules/${rule.id}`, { method: "DELETE" }), "Правило удалено")}>×</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </section>
  );
}
