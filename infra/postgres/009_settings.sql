INSERT INTO color_schemes(name, colors_json, patterns_enabled) VALUES
('Высокий контраст', '{"PRODUCTIVE":"#006400","NEUTRAL":"#455A64","UNPRODUCTIVE":"#FF8C00","IDLE":"#B00020","LOCKED":"#5D0011","BREAK":"#0066CC","ABSENCE":"#6A1B9A","OFFLINE":"#616161"}'::jsonb, true),
('Дальтоник-френдли', '{"PRODUCTIVE":"#0072B2","NEUTRAL":"#999999","UNPRODUCTIVE":"#E69F00","IDLE":"#D55E00","LOCKED":"#8B3A00","BREAK":"#56B4E9","ABSENCE":"#CC79A7","OFFLINE":"#777777"}'::jsonb, true),
('Тёмная', '{"PRODUCTIVE":"#66BB6A","NEUTRAL":"#90A4AE","UNPRODUCTIVE":"#FFCA28","IDLE":"#EF5350","LOCKED":"#B71C1C","BREAK":"#29B6F6","ABSENCE":"#AB47BC","OFFLINE":"#757575"}'::jsonb, false)
ON CONFLICT(name) DO NOTHING;

INSERT INTO settings(key,value_json) SELECT 'appearance.default',
    jsonb_build_object('color_scheme_id',c.id,'threshold_scheme_id',t.id)
FROM color_schemes c CROSS JOIN threshold_schemes t
WHERE c.is_default=true AND t.is_default=true
ON CONFLICT(key) DO NOTHING;

CREATE INDEX IF NOT EXISTS audit_log_created_action_idx ON audit_log(created_at DESC, action);
