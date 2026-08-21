CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS departments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    parent_id uuid REFERENCES departments(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (parent_id IS NULL OR parent_id <> id)
);

CREATE TABLE IF NOT EXISTS employees (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name text NOT NULL,
    email text,
    department_id uuid REFERENCES departments(id),
    department_name text,
    position_title text,
    hire_date date,
    timezone text NOT NULL DEFAULT 'UTC',
    planned_daily_minutes integer NOT NULL DEFAULT 480
        CHECK (planned_daily_minutes BETWEEN 0 AND 1440),
    status text NOT NULL DEFAULT 'active',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS employees_department_id_idx ON employees(department_id);
CREATE UNIQUE INDEX IF NOT EXISTS employees_email_unique_idx
    ON employees(lower(email)) WHERE email IS NOT NULL;

CREATE TABLE IF NOT EXISTS devices (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid REFERENCES employees(id),
    hostname text NOT NULL,
    machine_guid text NOT NULL UNIQUE,
    os_version text NOT NULL,
    agent_version text NOT NULL,
    token_hash text NOT NULL,
    is_approved boolean NOT NULL DEFAULT false,
    last_seen timestamptz,
    last_activity_state text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS devices_employee_id_idx ON devices(employee_id);
CREATE INDEX IF NOT EXISTS devices_last_seen_idx ON devices(last_seen DESC);

CREATE TABLE IF NOT EXISTS audit_log (
    id bigserial PRIMARY KEY,
    action text NOT NULL,
    object_type text NOT NULL,
    object_id text,
    details_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS activity_events (
    id bigserial PRIMARY KEY,
    event_uuid uuid NOT NULL UNIQUE,
    device_id uuid NOT NULL REFERENCES devices(id),
    employee_id uuid REFERENCES employees(id),
    ts_start timestamptz NOT NULL,
    ts_end timestamptz NOT NULL,
    duration_sec integer NOT NULL CHECK (duration_sec > 0),
    state text NOT NULL CHECK (
        state IN ('PRODUCTIVE', 'NEUTRAL', 'UNPRODUCTIVE', 'IDLE', 'LOCKED', 'BREAK')
    ),
    process_name text,
    app_name text,
    window_title text,
    url_domain text,
    url_path text,
    windows_session_id integer,
    is_remote boolean NOT NULL DEFAULT false,
    keystrokes integer NOT NULL DEFAULT 0 CHECK (keystrokes >= 0),
    clicks integer NOT NULL DEFAULT 0 CHECK (clicks >= 0),
    mouse_distance integer NOT NULL DEFAULT 0 CHECK (mouse_distance >= 0),
    received_at timestamptz NOT NULL DEFAULT now(),
    CHECK (ts_end > ts_start)
);

CREATE INDEX IF NOT EXISTS activity_events_employee_time_idx
    ON activity_events(employee_id, ts_start DESC);
CREATE INDEX IF NOT EXISTS activity_events_device_time_idx
    ON activity_events(device_id, ts_start);

CREATE TABLE IF NOT EXISTS categories (
    id bigserial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    productivity text NOT NULL CHECK (productivity IN ('PRODUCTIVE', 'NEUTRAL', 'UNPRODUCTIVE')),
    color text NOT NULL DEFAULT '#78909C',
    is_system boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rules (
    id bigserial PRIMARY KEY,
    priority integer NOT NULL,
    match_field text NOT NULL CHECK (
        match_field IN ('process_name', 'window_title', 'url_domain', 'url_full', 'file_path')
    ),
    match_type text NOT NULL CHECK (match_type IN ('exact', 'contains', 'wildcard', 'regex')),
    pattern text NOT NULL,
    category_id bigint NOT NULL REFERENCES categories(id),
    scope_type text NOT NULL DEFAULT 'global',
    scope_id uuid,
    schedule_json jsonb,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS rules_enabled_priority_idx ON rules(enabled, priority);

ALTER TABLE activity_events
    ADD COLUMN IF NOT EXISTS category_id bigint REFERENCES categories(id);

CREATE TABLE IF NOT EXISTS settings (
    key text PRIMARY KEY,
    value_json jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS roles (
    code text PRIMARY KEY,
    name text NOT NULL,
    is_system boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS permissions (
    code text PRIMARY KEY,
    description text NOT NULL
);

CREATE TABLE IF NOT EXISTS role_permissions (
    role_code text NOT NULL REFERENCES roles(code) ON DELETE CASCADE,
    permission_code text NOT NULL REFERENCES permissions(code) ON DELETE CASCADE,
    PRIMARY KEY(role_code, permission_code)
);

CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    login text NOT NULL,
    display_name text NOT NULL,
    password_hash text NOT NULL,
    role_code text NOT NULL REFERENCES roles(code),
    employee_id uuid REFERENCES employees(id),
    scope_type text NOT NULL DEFAULT 'organization'
        CHECK (scope_type IN ('organization', 'department', 'employee')),
    is_active boolean NOT NULL DEFAULT true,
    failed_login_attempts integer NOT NULL DEFAULT 0,
    locked_until timestamptz,
    totp_secret text,
    totp_confirmed_at timestamptz,
    last_login_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS users_login_unique_idx ON users(lower(login));
CREATE UNIQUE INDEX IF NOT EXISTS users_employee_unique_idx
    ON users(employee_id) WHERE employee_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS user_department_scope (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    department_id uuid NOT NULL REFERENCES departments(id) ON DELETE CASCADE,
    PRIMARY KEY(user_id, department_id)
);

CREATE TABLE IF NOT EXISTS user_employee_scope (
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    PRIMARY KEY(user_id, employee_id)
);

CREATE TABLE IF NOT EXISTS refresh_sessions (
    id uuid PRIMARY KEY,
    family_id uuid NOT NULL,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash text NOT NULL,
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    replaced_by uuid,
    ip_address inet,
    user_agent text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS refresh_sessions_user_idx ON refresh_sessions(user_id, expires_at DESC);
CREATE INDEX IF NOT EXISTS refresh_sessions_family_idx ON refresh_sessions(family_id);

INSERT INTO roles(code, name) VALUES
    ('superadmin', 'Суперадминистратор'),
    ('admin', 'Администратор'),
    ('hr', 'HR'),
    ('manager', 'Руководитель'),
    ('observer', 'Наблюдатель'),
    ('employee', 'Сотрудник')
ON CONFLICT(code) DO NOTHING;

INSERT INTO permissions(code, description) VALUES
    ('presence:view', 'Просмотр текущего присутствия'),
    ('timeline:view', 'Просмотр таймлайна'),
    ('reports:view', 'Просмотр отчётов'),
    ('screenshot:view', 'Просмотр скриншотов'),
    ('screenshot:export', 'Экспорт скриншотов'),
    ('stream:live', 'Просмотр live-трансляций'),
    ('stream:archive', 'Просмотр архива видео'),
    ('stream:download', 'Скачивание видео'),
    ('absence:manage', 'Управление отсутствиями'),
    ('settings:manage', 'Управление настройками и справочниками'),
    ('users:manage', 'Управление пользователями и ролями'),
    ('audit:view', 'Просмотр журнала аудита')
ON CONFLICT(code) DO NOTHING;

INSERT INTO role_permissions(role_code, permission_code)
SELECT role_code, permission_code
FROM (VALUES
    ('superadmin', 'presence:view'), ('superadmin', 'timeline:view'), ('superadmin', 'reports:view'),
    ('superadmin', 'screenshot:view'), ('superadmin', 'screenshot:export'), ('superadmin', 'stream:live'),
    ('superadmin', 'stream:archive'), ('superadmin', 'stream:download'), ('superadmin', 'absence:manage'),
    ('superadmin', 'settings:manage'), ('superadmin', 'users:manage'), ('superadmin', 'audit:view'),
    ('admin', 'presence:view'), ('admin', 'timeline:view'), ('admin', 'reports:view'),
    ('admin', 'screenshot:view'), ('admin', 'screenshot:export'), ('admin', 'stream:live'),
    ('admin', 'stream:archive'), ('admin', 'stream:download'), ('admin', 'absence:manage'),
    ('admin', 'settings:manage'), ('admin', 'users:manage'), ('admin', 'audit:view'),
    ('hr', 'presence:view'), ('hr', 'timeline:view'), ('hr', 'reports:view'), ('hr', 'absence:manage'),
    ('manager', 'presence:view'), ('manager', 'timeline:view'), ('manager', 'reports:view'),
    ('manager', 'screenshot:view'), ('manager', 'stream:live'), ('manager', 'stream:archive'),
    ('manager', 'absence:manage'),
    ('observer', 'presence:view'), ('observer', 'timeline:view'), ('observer', 'reports:view'),
    ('employee', 'presence:view'), ('employee', 'timeline:view')
) AS seeded(role_code, permission_code)
ON CONFLICT DO NOTHING;

INSERT INTO categories(code, name, productivity, color, is_system) VALUES
    ('uncategorized', 'Без категории', 'NEUTRAL', '#78909C', true),
    ('development', 'Разработка', 'PRODUCTIVE', '#2E7D32', true),
    ('office', 'Офисные приложения', 'PRODUCTIVE', '#43A047', true),
    ('social', 'Социальные сети', 'UNPRODUCTIVE', '#EF6C00', true),
    ('video', 'Видео и короткие ролики', 'UNPRODUCTIVE', '#F9A825', true)
ON CONFLICT(code) DO NOTHING;

INSERT INTO rules(priority, match_field, match_type, pattern, category_id)
SELECT seed.priority, seed.match_field, seed.match_type, seed.pattern, categories.id
FROM (VALUES
    (5,  'url_full',    'contains', 'youtube.com/shorts',  'video'),
    (6,  'url_full',    'contains', 'instagram.com/reels', 'video'),
    (7,  'url_full',    'contains', 'vk.com/clips',         'video'),
    (10, 'url_domain',  'exact',    'tiktok.com',   'video'),
    (20, 'url_domain',  'exact',    'youtube.com',  'video'),
    (30, 'url_domain',  'exact',    'vk.com',       'social'),
    (40, 'process_name','exact',    'code.exe',     'development'),
    (41, 'process_name','exact',    'devenv.exe',   'development'),
    (42, 'process_name','exact',    'rider64.exe',  'development'),
    (50, 'process_name','exact',    'winword.exe',  'office'),
    (51, 'process_name','exact',    'excel.exe',    'office'),
    (52, 'process_name','exact',    'powerpnt.exe', 'office')
) AS seed(priority, match_field, match_type, pattern, category_code)
JOIN categories ON categories.code = seed.category_code
WHERE NOT EXISTS (
    SELECT 1 FROM rules
    WHERE rules.priority = seed.priority
      AND rules.match_field = seed.match_field
      AND rules.pattern = seed.pattern
);

INSERT INTO settings(key, value_json) VALUES (
    'agent.default',
    '{
      "activity_poll_interval_sec": 2,
      "idle_threshold_sec": 300,
      "batch_interval_sec": 60,
      "batch_size": 500,
      "collect_window_titles": true,
      "collect_browser_urls": true,
      "personal_time_enabled": true
      ,"screenshot_enabled": true
      ,"screenshot_interval_sec": 300
      ,"screenshot_random_offset": true
      ,"screenshot_all_monitors": false
      ,"screenshot_multi_monitor_mode": "merge"
      ,"screenshot_max_long_side": 1600
      ,"screenshot_quality": 70
      ,"screenshot_on_unproductive": false
      ,"screenshot_blur_mode": "none"
      ,"private_app_patterns": ["keepass","1password","bitwarden","bank","банк-клиент"]
      ,"schedule_grace_minutes": 60
      ,"collect_outside_schedule_activity": true
      ,"treat_media_playback_as_activity": true
      ,"video_recording_mode": "on_demand"
      ,"video_profile": "medium"
      ,"video_schedule_windows": []
      ,"video_trigger_minutes": 5
      ,"video_on_demand_timeout_minutes": 30
      ,"privacy_contact": "Ответственный назначается работодателем"
      ,"privacy_retention_notice": "События 365 дней, скриншоты 30 дней, видео 7 дней"
    }'::jsonb
)
ON CONFLICT(key) DO NOTHING;


CREATE TABLE IF NOT EXISTS windows_accounts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id uuid NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    sid text NOT NULL,
    username text NOT NULL,
    employee_id uuid REFERENCES employees(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(device_id, sid)
);

CREATE TABLE IF NOT EXISTS activity_daily (
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    activity_date date NOT NULL,
    plan_sec integer NOT NULL DEFAULT 0,
    online_sec integer NOT NULL DEFAULT 0,
    productive_sec integer NOT NULL DEFAULT 0,
    neutral_sec integer NOT NULL DEFAULT 0,
    unproductive_sec integer NOT NULL DEFAULT 0,
    idle_sec integer NOT NULL DEFAULT 0,
    absence_sec integer NOT NULL DEFAULT 0,
    first_activity_at timestamptz,
    last_activity_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(employee_id, activity_date)
);

CREATE TABLE IF NOT EXISTS screenshots (
    id bigserial PRIMARY KEY,
    employee_id uuid REFERENCES employees(id),
    device_id uuid NOT NULL REFERENCES devices(id),
    taken_at timestamptz NOT NULL,
    monitor_index integer NOT NULL DEFAULT 0,
    storage_key text,
    thumb_key text,
    width integer NOT NULL CHECK (width > 0),
    height integer NOT NULL CHECK (height > 0),
    size_bytes bigint NOT NULL DEFAULT 0,
    phash text,
    duplicate_of_id bigint REFERENCES screenshots(id),
    is_blurred boolean NOT NULL DEFAULT false,
    activity_event_id bigint REFERENCES activity_events(id),
    state text,
    category_id bigint REFERENCES categories(id),
    app_name text,
    url_domain text,
    expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (storage_key IS NOT NULL OR duplicate_of_id IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS screenshots_employee_taken_idx ON screenshots(employee_id, taken_at DESC);
CREATE INDEX IF NOT EXISTS screenshots_device_taken_idx ON screenshots(device_id, taken_at DESC);

CREATE TABLE IF NOT EXISTS stream_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id uuid NOT NULL REFERENCES devices(id),
    employee_id uuid REFERENCES employees(id),
    started_at timestamptz NOT NULL DEFAULT now(),
    ended_at timestamptz,
    profile text NOT NULL DEFAULT 'medium' CHECK (profile IN ('low', 'medium', 'high')),
    status text NOT NULL DEFAULT 'requested' CHECK (status IN ('requested', 'starting', 'live', 'ended', 'failed')),
    storage_prefix text,
    initiated_by uuid REFERENCES users(id),
    mode text NOT NULL DEFAULT 'on_demand' CHECK (mode IN ('always_on', 'on_demand', 'scheduled', 'trigger')),
    stream_key text NOT NULL UNIQUE,
    failure_reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS stream_sessions_employee_time_idx ON stream_sessions(employee_id, started_at DESC);

CREATE TABLE IF NOT EXISTS stream_segments (
    id bigserial PRIMARY KEY,
    session_id uuid NOT NULL REFERENCES stream_sessions(id) ON DELETE CASCADE,
    seq integer NOT NULL,
    ts_start timestamptz NOT NULL,
    duration_ms integer NOT NULL CHECK (duration_ms > 0),
    storage_key text NOT NULL,
    size_bytes bigint NOT NULL DEFAULT 0,
    expires_at timestamptz,
    is_pinned boolean NOT NULL DEFAULT false,
    pin_reason text,
    pin_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(session_id, seq)
);
CREATE INDEX IF NOT EXISTS stream_segments_session_seq_idx ON stream_segments(session_id, seq);

CREATE TABLE IF NOT EXISTS absence_types (
    id bigserial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    color text NOT NULL,
    effect text NOT NULL DEFAULT 'neutral'
        CHECK (effect IN ('excludes_day', 'counts_as_violation', 'adds_plan_time', 'neutral')),
    requires_document boolean NOT NULL DEFAULT false,
    is_system boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS absences (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id),
    type_id bigint NOT NULL REFERENCES absence_types(id),
    date_from date NOT NULL,
    date_to date NOT NULL,
    minutes integer,
    reason text,
    comment text,
    attachment_key text,
    severity integer CHECK (severity BETWEEN 1 AND 5),
    status text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'pending', 'approved', 'rejected')),
    is_auto boolean NOT NULL DEFAULT false,
    created_by uuid REFERENCES users(id),
    approved_by uuid REFERENCES users(id),
    approved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (date_to >= date_from)
);
CREATE INDEX IF NOT EXISTS absences_employee_dates_idx ON absences(employee_id, date_from, date_to);
CREATE INDEX IF NOT EXISTS absences_status_idx ON absences(status, date_from);

CREATE TABLE IF NOT EXISTS schedules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    kind text NOT NULL CHECK (kind IN ('fixed', 'shift', 'flexible', 'individual')),
    rules_json jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS schedule_assignments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id),
    schedule_id uuid NOT NULL REFERENCES schedules(id),
    valid_from date NOT NULL,
    valid_to date,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE INDEX IF NOT EXISTS schedule_assignments_employee_dates_idx
    ON schedule_assignments(employee_id, valid_from DESC, valid_to);

CREATE TABLE IF NOT EXISTS holidays (
    holiday_date date PRIMARY KEY,
    name text NOT NULL,
    kind text NOT NULL DEFAULT 'holiday' CHECK (kind IN ('holiday', 'working', 'shortened'))
);

CREATE TABLE IF NOT EXISTS color_schemes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    colors_json jsonb NOT NULL,
    patterns_enabled boolean NOT NULL DEFAULT false,
    is_default boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS threshold_schemes (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL UNIQUE,
    rules_json jsonb NOT NULL,
    scope_type text NOT NULL DEFAULT 'global' CHECK (scope_type IN ('global', 'department', 'employee')),
    scope_id uuid,
    is_default boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scoped_settings (
    key text NOT NULL,
    scope_type text NOT NULL DEFAULT 'global' CHECK (scope_type IN ('global', 'department', 'employee')),
    scope_id uuid,
    value_json jsonb NOT NULL,
    updated_by uuid REFERENCES users(id),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT(key, scope_type, scope_id)
);

CREATE TABLE IF NOT EXISTS retention_policies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    data_type text NOT NULL CHECK (data_type IN ('screenshots', 'video', 'events')),
    scope_type text NOT NULL DEFAULT 'global' CHECK (scope_type IN ('global', 'department', 'employee')),
    scope_id uuid,
    days integer NOT NULL CHECK (days BETWEEN 1 AND 3650),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE NULLS NOT DISTINCT(data_type, scope_type, scope_id)
);

CREATE TABLE IF NOT EXISTS agent_commands (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id uuid NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    command text NOT NULL,
    payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'delivered', 'acknowledged', 'failed', 'expired')),
    requested_by uuid REFERENCES users(id),
    requested_at timestamptz NOT NULL DEFAULT now(),
    delivered_at timestamptz,
    acknowledged_at timestamptz,
    expires_at timestamptz NOT NULL DEFAULT (now() + interval '10 minutes')
);
CREATE INDEX IF NOT EXISTS agent_commands_device_status_idx ON agent_commands(device_id, status, requested_at);

CREATE TABLE IF NOT EXISTS notifications (
    id bigserial PRIMARY KEY,
    user_id uuid REFERENCES users(id) ON DELETE CASCADE,
    notification_type text NOT NULL,
    payload_json jsonb NOT NULL,
    is_read boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notifications_user_unread_idx ON notifications(user_id, is_read, created_at DESC);

CREATE TABLE IF NOT EXISTS saved_report_presets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name text NOT NULL,
    report_code text NOT NULL,
    filters_json jsonb NOT NULL,
    columns_json jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS report_schedules (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users(id),
    report_code text NOT NULL,
    filters_json jsonb NOT NULL,
    recipients text[] NOT NULL,
    cron text NOT NULL,
    format text NOT NULL CHECK (format IN ('csv', 'xlsx', 'pdf')),
    enabled boolean NOT NULL DEFAULT true,
    last_run_at timestamptz,
    next_run_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS report_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    schedule_id uuid REFERENCES report_schedules(id) ON DELETE SET NULL,
    report_code text NOT NULL,
    status text NOT NULL CHECK (status IN ('queued', 'running', 'sent', 'failed')),
    recipients text[],
    storage_key text,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS user_id uuid REFERENCES users(id);
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS target_employee_id uuid REFERENCES employees(id);
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS ip_address inet;
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS user_agent text;

INSERT INTO absence_types(code, name, color, effect, requires_document, is_system) VALUES
    ('VACATION', 'Отпуск оплачиваемый', '#43A047', 'excludes_day', false, true),
    ('VACATION_UNPAID', 'Отпуск за свой счёт', '#8D6E63', 'excludes_day', false, true),
    ('SICK_LEAVE', 'Больничный', '#EF5350', 'excludes_day', true, true),
    ('DAY_OFF', 'Отгул', '#26A69A', 'excludes_day', false, true),
    ('REMOTE', 'Удалённая работа', '#42A5F5', 'neutral', false, true),
    ('BUSINESS_TRIP', 'Командировка', '#7E57C2', 'neutral', false, true),
    ('LATE_VALID', 'Опоздание уважительное', '#FFB74D', 'neutral', true, true),
    ('LATE_INVALID', 'Опоздание неуважительное', '#FB8C00', 'counts_as_violation', false, true),
    ('EARLY_LEAVE', 'Ранний уход', '#F4511E', 'counts_as_violation', false, true),
    ('ABSENCE_UNEXCUSED', 'Прогул', '#C62828', 'counts_as_violation', false, true),
    ('VIOLATION', 'Нарушение', '#AD1457', 'counts_as_violation', false, true),
    ('OVERTIME', 'Переработка', '#00897B', 'adds_plan_time', false, true)
ON CONFLICT(code) DO NOTHING;

INSERT INTO schedules(name, kind, rules_json) VALUES (
    'Стандартный 5/2',
    'fixed',
    '{"weekdays":[1,2,3,4,5],"start":"09:00","end":"18:00","break_minutes":60,"late_tolerance_minutes":5}'::jsonb
) ON CONFLICT(name) DO NOTHING;

INSERT INTO color_schemes(name, colors_json, is_default) VALUES (
    'Стандартная',
    '{"PRODUCTIVE":"#2E7D32","NEUTRAL":"#78909C","UNPRODUCTIVE":"#F9A825","IDLE":"#C62828","LOCKED":"#8F2525","BREAK":"#0288D1","ABSENCE":"#7E57C2","OFFLINE":"#9E9E9E"}'::jsonb,
    true
) ON CONFLICT(name) DO NOTHING;

INSERT INTO threshold_schemes(name, rules_json, is_default) VALUES (
    'Стандартная оценка',
    '[{"min":75,"code":"GOOD","label":"В норме","color":"#2E7D32"},{"min":50,"code":"ATTENTION","label":"Внимание","color":"#F9A825"},{"min":0,"code":"RISK","label":"Риск","color":"#C62828"}]'::jsonb,
    true
) ON CONFLICT DO NOTHING;

INSERT INTO retention_policies(data_type, days) VALUES
    ('screenshots', 30), ('video', 7), ('events', 365)
ON CONFLICT DO NOTHING;

INSERT INTO permissions(code, description) VALUES
    ('absence:request', 'Создание и просмотр собственных заявок на отсутствие')
ON CONFLICT(code) DO NOTHING;

INSERT INTO role_permissions(role_code, permission_code) VALUES
    ('superadmin','absence:request'), ('admin','absence:request'), ('hr','absence:request'),
    ('manager','absence:request'), ('employee','absence:request')
ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS vacation_balances (
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    balance_year integer NOT NULL CHECK (balance_year BETWEEN 2000 AND 2200),
    opening_days numeric(6,2) NOT NULL DEFAULT 0,
    accrued_days numeric(6,2) NOT NULL DEFAULT 0,
    used_days numeric(6,2) NOT NULL DEFAULT 0,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(employee_id, balance_year)
);

INSERT INTO color_schemes(name, colors_json, patterns_enabled) VALUES
('Высокий контраст', '{"PRODUCTIVE":"#006400","NEUTRAL":"#455A64","UNPRODUCTIVE":"#FF8C00","IDLE":"#B00020","LOCKED":"#5D0011","BREAK":"#0066CC","ABSENCE":"#6A1B9A","OFFLINE":"#616161"}'::jsonb, true),
('Дальтоник-френдли', '{"PRODUCTIVE":"#0072B2","NEUTRAL":"#999999","UNPRODUCTIVE":"#E69F00","IDLE":"#D55E00","LOCKED":"#8B3A00","BREAK":"#56B4E9","ABSENCE":"#CC79A7","OFFLINE":"#777777"}'::jsonb, true),
('Тёмная', '{"PRODUCTIVE":"#66BB6A","NEUTRAL":"#90A4AE","UNPRODUCTIVE":"#FFCA28","IDLE":"#EF5350","LOCKED":"#B71C1C","BREAK":"#29B6F6","ABSENCE":"#AB47BC","OFFLINE":"#757575"}'::jsonb, false)
ON CONFLICT(name) DO NOTHING;

INSERT INTO settings(key,value_json) SELECT 'appearance.default',
    jsonb_build_object('color_scheme_id',c.id,'threshold_scheme_id',t.id)
FROM color_schemes c CROSS JOIN threshold_schemes t
WHERE c.is_default=true AND t.is_default=true
ON CONFLICT(key) DO NOTHING;

CREATE INDEX IF NOT EXISTS audit_log_created_action_idx ON audit_log(created_at DESC, action);

CREATE TABLE IF NOT EXISTS pinned_video_ranges (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    employee_id uuid NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    range_start timestamptz NOT NULL,
    range_end timestamptz NOT NULL,
    reason text,
    pinned_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK(range_end > range_start)
);
CREATE INDEX IF NOT EXISTS pinned_video_ranges_lookup_idx ON pinned_video_ranges(employee_id,range_start,range_end);

CREATE OR REPLACE FUNCTION reject_audit_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END;
$$;
DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log;
CREATE TRIGGER audit_log_append_only BEFORE UPDATE OR DELETE ON audit_log
FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE INDEX IF NOT EXISTS devices_token_hash_idx ON devices(token_hash);
ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS windows_sid text;
ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS windows_username text;
ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS is_quarantined boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS activity_events_quarantine_idx ON activity_events(device_id,is_quarantined,ts_start DESC) WHERE is_quarantined=true;

CREATE TABLE IF NOT EXISTS agent_diagnostics (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id uuid NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    storage_key text NOT NULL,
    size_bytes bigint NOT NULL CHECK(size_bytes >= 0),
    reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_diagnostics_device_created_idx ON agent_diagnostics(device_id,created_at DESC);

CREATE TABLE IF NOT EXISTS update_releases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version text NOT NULL UNIQUE,
    storage_key text NOT NULL,
    sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
    rollout_percent integer NOT NULL DEFAULT 5 CHECK(rollout_percent BETWEEN 0 AND 100),
    minimum_agent_version text,
    maintenance_start_hour integer NOT NULL DEFAULT 1 CHECK(maintenance_start_hour BETWEEN 0 AND 23),
    maintenance_end_hour integer NOT NULL DEFAULT 5 CHECK(maintenance_end_hour BETWEEN 0 AND 23),
    is_active boolean NOT NULL DEFAULT false,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS reclassification_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    days integer NOT NULL CHECK(days BETWEEN 1 AND 365),
    status text NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','completed','failed')),
    total_events bigint NOT NULL DEFAULT 0,
    processed_events bigint NOT NULL DEFAULT 0,
    error text,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz
);
CREATE INDEX IF NOT EXISTS reclassification_jobs_status_idx ON reclassification_jobs(status,created_at);
ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS time_skew boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS activity_events_time_skew_idx ON activity_events(device_id,ts_start DESC) WHERE time_skew=true;
