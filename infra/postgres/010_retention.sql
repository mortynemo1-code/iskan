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
