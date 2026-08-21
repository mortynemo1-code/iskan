ALTER TABLE employees
    ADD COLUMN IF NOT EXISTS planned_daily_minutes integer NOT NULL DEFAULT 480;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'employees_planned_daily_minutes_check'
    ) THEN
        ALTER TABLE employees
            ADD CONSTRAINT employees_planned_daily_minutes_check
            CHECK (planned_daily_minutes BETWEEN 0 AND 1440);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS activity_events_time_employee_idx
    ON activity_events(ts_start, ts_end, employee_id);
