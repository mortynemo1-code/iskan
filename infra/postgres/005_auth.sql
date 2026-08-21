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
    ('superadmin', 'Суперадминистратор'), ('admin', 'Администратор'), ('hr', 'HR'),
    ('manager', 'Руководитель'), ('observer', 'Наблюдатель'), ('employee', 'Сотрудник')
ON CONFLICT(code) DO NOTHING;

INSERT INTO permissions(code, description) VALUES
    ('presence:view', 'Просмотр текущего присутствия'), ('timeline:view', 'Просмотр таймлайна'),
    ('reports:view', 'Просмотр отчётов'), ('screenshot:view', 'Просмотр скриншотов'),
    ('screenshot:export', 'Экспорт скриншотов'), ('stream:live', 'Просмотр live-трансляций'),
    ('stream:archive', 'Просмотр архива видео'), ('stream:download', 'Скачивание видео'),
    ('absence:manage', 'Управление отсутствиями'), ('settings:manage', 'Управление настройками и справочниками'),
    ('users:manage', 'Управление пользователями и ролями'), ('audit:view', 'Просмотр журнала аудита')
ON CONFLICT(code) DO NOTHING;

INSERT INTO role_permissions(role_code, permission_code)
SELECT role_code, permission_code FROM (VALUES
    ('superadmin', 'presence:view'), ('superadmin', 'timeline:view'), ('superadmin', 'reports:view'), ('superadmin', 'screenshot:view'), ('superadmin', 'screenshot:export'), ('superadmin', 'stream:live'), ('superadmin', 'stream:archive'), ('superadmin', 'stream:download'), ('superadmin', 'absence:manage'), ('superadmin', 'settings:manage'), ('superadmin', 'users:manage'), ('superadmin', 'audit:view'),
    ('admin', 'presence:view'), ('admin', 'timeline:view'), ('admin', 'reports:view'), ('admin', 'screenshot:view'), ('admin', 'screenshot:export'), ('admin', 'stream:live'), ('admin', 'stream:archive'), ('admin', 'stream:download'), ('admin', 'absence:manage'), ('admin', 'settings:manage'), ('admin', 'users:manage'), ('admin', 'audit:view'),
    ('hr', 'presence:view'), ('hr', 'timeline:view'), ('hr', 'reports:view'), ('hr', 'absence:manage'),
    ('manager', 'presence:view'), ('manager', 'timeline:view'), ('manager', 'reports:view'), ('manager', 'screenshot:view'), ('manager', 'stream:live'), ('manager', 'stream:archive'), ('manager', 'absence:manage'),
    ('observer', 'presence:view'), ('observer', 'timeline:view'), ('observer', 'reports:view'),
    ('employee', 'presence:view'), ('employee', 'timeline:view')
) AS seeded(role_code, permission_code)
ON CONFLICT DO NOTHING;
