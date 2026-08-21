
ALTER TABLE employees ADD COLUMN IF NOT EXISTS position_title text;
ALTER TABLE employees ADD COLUMN IF NOT EXISTS hire_date date;

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
