CREATE TABLE IF NOT EXISTS agent_diagnostics (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id uuid NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    storage_key text NOT NULL,
    size_bytes bigint NOT NULL CHECK(size_bytes >= 0),
    reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS agent_diagnostics_device_created_idx ON agent_diagnostics(device_id,created_at DESC);

CREATE TABLE IF NOT EXISTS update_releases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    version text NOT NULL UNIQUE,
    storage_key text NOT NULL,
    sha256 text NOT NULL CHECK(sha256 ~ '^[0-9a-f]{64}$'),
    rollout_percent integer NOT NULL DEFAULT 5 CHECK(rollout_percent BETWEEN 0 AND 100),
    minimum_agent_version text,
    maintenance_start_hour integer NOT NULL DEFAULT 1 CHECK(maintenance_start_hour BETWEEN 0 AND 23),
    maintenance_end_hour integer NOT NULL DEFAULT 5 CHECK(maintenance_end_hour BETWEEN 0 AND 23),
    is_active boolean NOT NULL DEFAULT false,
    created_by uuid REFERENCES users(id),
    created_at timestamptz NOT NULL DEFAULT now()
);
