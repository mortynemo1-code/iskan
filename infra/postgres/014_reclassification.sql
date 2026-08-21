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
