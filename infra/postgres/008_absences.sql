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
