-- Для уже созданной development-БД. На чистой установке таблица создаётся init.sql.
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

ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS window_title text;
