ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS windows_sid text;
ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS windows_username text;
ALTER TABLE activity_events ADD COLUMN IF NOT EXISTS is_quarantined boolean NOT NULL DEFAULT false;
CREATE INDEX IF NOT EXISTS activity_events_quarantine_idx ON activity_events(device_id,is_quarantined,ts_start DESC) WHERE is_quarantined=true;
