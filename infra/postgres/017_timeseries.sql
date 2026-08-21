CREATE EXTENSION IF NOT EXISTS timescaledb;

-- A write-through time-series projection keeps the transactional activity table
-- compatible with screenshot foreign keys while enabling hypertables and
-- continuous aggregates for large-period charts and reports.
CREATE TABLE IF NOT EXISTS activity_samples (
    event_uuid uuid NOT NULL,
    device_id uuid NOT NULL,
    employee_id uuid,
    ts_start timestamptz NOT NULL,
    duration_sec integer NOT NULL CHECK (duration_sec > 0),
    state text NOT NULL,
    category_id bigint,
    PRIMARY KEY (event_uuid, ts_start)
);

SELECT create_hypertable('activity_samples', by_range('ts_start'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS activity_samples_employee_time_idx ON activity_samples(employee_id, ts_start DESC);
CREATE INDEX IF NOT EXISTS activity_samples_device_time_idx ON activity_samples(device_id, ts_start DESC);

INSERT INTO activity_samples(event_uuid,device_id,employee_id,ts_start,duration_sec,state,category_id)
SELECT event_uuid,device_id,employee_id,ts_start,duration_sec,state,category_id FROM activity_events
ON CONFLICT(event_uuid,ts_start) DO UPDATE SET
  employee_id=EXCLUDED.employee_id,duration_sec=EXCLUDED.duration_sec,state=EXCLUDED.state,category_id=EXCLUDED.category_id;

CREATE OR REPLACE FUNCTION mirror_activity_sample() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO activity_samples(event_uuid,device_id,employee_id,ts_start,duration_sec,state,category_id)
  VALUES(NEW.event_uuid,NEW.device_id,NEW.employee_id,NEW.ts_start,NEW.duration_sec,NEW.state,NEW.category_id)
  ON CONFLICT(event_uuid,ts_start) DO UPDATE SET
    employee_id=EXCLUDED.employee_id,duration_sec=EXCLUDED.duration_sec,state=EXCLUDED.state,category_id=EXCLUDED.category_id;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS activity_samples_mirror ON activity_events;
CREATE TRIGGER activity_samples_mirror AFTER INSERT OR UPDATE OF employee_id,duration_sec,state,category_id
ON activity_events FOR EACH ROW EXECUTE FUNCTION mirror_activity_sample();

CREATE MATERIALIZED VIEW IF NOT EXISTS activity_1m
WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '1 minute', ts_start) AS bucket, employee_id, state, category_id,
       sum(duration_sec)::bigint AS duration_sec, count(*)::bigint AS event_count
FROM activity_samples GROUP BY bucket,employee_id,state,category_id WITH NO DATA;
CREATE MATERIALIZED VIEW IF NOT EXISTS activity_5m
WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '5 minutes', ts_start) AS bucket, employee_id, state, category_id,
       sum(duration_sec)::bigint AS duration_sec, count(*)::bigint AS event_count
FROM activity_samples GROUP BY bucket,employee_id,state,category_id WITH NO DATA;
CREATE MATERIALIZED VIEW IF NOT EXISTS activity_1h
WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '1 hour', ts_start) AS bucket, employee_id, state, category_id,
       sum(duration_sec)::bigint AS duration_sec, count(*)::bigint AS event_count
FROM activity_samples GROUP BY bucket,employee_id,state,category_id WITH NO DATA;
CREATE MATERIALIZED VIEW IF NOT EXISTS activity_1d
WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '1 day', ts_start) AS bucket, employee_id, state, category_id,
       sum(duration_sec)::bigint AS duration_sec, count(*)::bigint AS event_count
FROM activity_samples GROUP BY bucket,employee_id,state,category_id WITH NO DATA;

SELECT add_continuous_aggregate_policy('activity_1m', start_offset => INTERVAL '7 days', end_offset => INTERVAL '1 minute', schedule_interval => INTERVAL '1 minute', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('activity_5m', start_offset => INTERVAL '31 days', end_offset => INTERVAL '5 minutes', schedule_interval => INTERVAL '5 minutes', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('activity_1h', start_offset => INTERVAL '365 days', end_offset => INTERVAL '1 hour', schedule_interval => INTERVAL '1 hour', if_not_exists => TRUE);
SELECT add_continuous_aggregate_policy('activity_1d', start_offset => INTERVAL '5 years', end_offset => INTERVAL '1 day', schedule_interval => INTERVAL '1 day', if_not_exists => TRUE);

UPDATE settings SET value_json=value_json || '{
  "screenshot_multi_monitor_mode":"merge",
  "video_recording_mode":"on_demand",
  "video_profile":"medium",
  "video_schedule_windows":[],
  "video_trigger_minutes":5,
  "video_on_demand_timeout_minutes":30
}'::jsonb, updated_at=now() WHERE key='agent.default';
