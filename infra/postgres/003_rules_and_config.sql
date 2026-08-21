CREATE TABLE IF NOT EXISTS categories (
    id bigserial PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    productivity text NOT NULL CHECK (productivity IN ('PRODUCTIVE', 'NEUTRAL', 'UNPRODUCTIVE')),
    is_system boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS rules (
    id bigserial PRIMARY KEY,
    priority integer NOT NULL,
    match_field text NOT NULL,
    match_type text NOT NULL,
    pattern text NOT NULL,
    category_id bigint NOT NULL REFERENCES categories(id),
    scope_type text NOT NULL DEFAULT 'global',
    scope_id uuid,
    schedule_json jsonb,
    enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS rules_enabled_priority_idx ON rules(enabled, priority);

ALTER TABLE activity_events
    ADD COLUMN IF NOT EXISTS category_id bigint REFERENCES categories(id);

CREATE TABLE IF NOT EXISTS settings (
    key text PRIMARY KEY,
    value_json jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO categories(code, name, productivity, is_system) VALUES
    ('uncategorized', 'Без категории', 'NEUTRAL', true),
    ('development', 'Разработка', 'PRODUCTIVE', true),
    ('office', 'Офисные приложения', 'PRODUCTIVE', true),
    ('social', 'Социальные сети', 'UNPRODUCTIVE', true),
    ('video', 'Видео и короткие ролики', 'UNPRODUCTIVE', true)
ON CONFLICT(code) DO NOTHING;

DELETE FROM rules
WHERE (priority, match_field, pattern) IN (
    (5, 'url_full', '/shorts'),
    (6, 'url_full', '/reels'),
    (7, 'url_full', '/clips')
);

INSERT INTO rules(priority, match_field, match_type, pattern, category_id)
SELECT seed.priority, seed.match_field, seed.match_type, seed.pattern, categories.id
FROM (VALUES
    (5, 'url_full', 'contains', 'youtube.com/shorts', 'video'),
    (6, 'url_full', 'contains', 'instagram.com/reels', 'video'),
    (7, 'url_full', 'contains', 'vk.com/clips', 'video'),
    (10, 'url_domain', 'exact', 'tiktok.com', 'video'),
    (20, 'url_domain', 'exact', 'youtube.com', 'video'),
    (30, 'url_domain', 'exact', 'vk.com', 'social'),
    (40, 'process_name', 'exact', 'code.exe', 'development'),
    (41, 'process_name', 'exact', 'devenv.exe', 'development'),
    (42, 'process_name', 'exact', 'rider64.exe', 'development'),
    (50, 'process_name', 'exact', 'winword.exe', 'office'),
    (51, 'process_name', 'exact', 'excel.exe', 'office'),
    (52, 'process_name', 'exact', 'powerpnt.exe', 'office')
) AS seed(priority, match_field, match_type, pattern, category_code)
JOIN categories ON categories.code = seed.category_code
WHERE NOT EXISTS (
    SELECT 1 FROM rules
    WHERE rules.priority = seed.priority
      AND rules.match_field = seed.match_field
      AND rules.pattern = seed.pattern
);

INSERT INTO settings(key, value_json) VALUES (
    'agent.default',
    '{
      "activity_poll_interval_sec": 2,
      "idle_threshold_sec": 300,
      "batch_interval_sec": 60,
      "batch_size": 500,
      "collect_window_titles": true,
      "collect_browser_urls": true,
      "personal_time_enabled": true
      ,"screenshot_enabled": true
      ,"screenshot_interval_sec": 300
      ,"screenshot_random_offset": true
      ,"screenshot_all_monitors": false
      ,"screenshot_multi_monitor_mode": "merge"
      ,"screenshot_max_long_side": 1600
      ,"screenshot_quality": 70
      ,"screenshot_on_unproductive": false
      ,"screenshot_blur_mode": "none"
      ,"private_app_patterns": ["keepass","1password","bitwarden","bank","банк-клиент"]
      ,"schedule_grace_minutes": 60
      ,"collect_outside_schedule_activity": true
      ,"treat_media_playback_as_activity": true
      ,"video_recording_mode": "on_demand"
      ,"video_profile": "medium"
      ,"video_schedule_windows": []
      ,"video_trigger_minutes": 5
      ,"video_on_demand_timeout_minutes": 30
      ,"privacy_contact": "Ответственный назначается работодателем"
      ,"privacy_retention_notice": "События 365 дней, скриншоты 30 дней, видео 7 дней"
    }'::jsonb
)
ON CONFLICT(key) DO NOTHING;
