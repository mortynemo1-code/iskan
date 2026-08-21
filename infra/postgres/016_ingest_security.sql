ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS time_skew boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS activity_events_time_skew_idx ON activity_events(device_id,ts_start DESC) WHERE time_skew=true;
