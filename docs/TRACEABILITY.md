# Матрица соответствия ТЗ

Матрица связывает обязательные блоки `TZ_workforce_monitoring.md` с реализацией и проверками. Это не акт приёмки на инфраструктуре заказчика: аппаратные SLA и юридические документы подтверждаются отдельно.

| Блок ТЗ | Реализация | Проверка |
|---|---|---|
| Правовой режим | disclosure/tray, личное время, график/праздники, запрет снимков/live, аудит просмотров и экспортов, выгрузка/удаление ПДн | unit/API + сценарии `ACCEPTANCE_TEST_PLAN.md` |
| Activity | Windows active window/UI Automation URL, input counters без кодов клавиш, NAudio media activity, агрегация, gzip batches, SQLite FIFO, UUID idempotency, clock-skew/quarantine | .NET tests в CI + backend tests |
| Online | heartbeat 30 с, Redis TTL 90 с, WebSocket presence, экран «Кто онлайн» | backend tests + simulator |
| Timeline | Canvas day/week, 100+ строк, zoom/pan, точные tooltips, lazy thumbnail 250 мс/cache, контекстные действия и deep links | TypeScript production build + ручной сценарий |
| Rules | process/title/domain/full URL/path, priority/scope/schedule, 300+ seed rules, Shorts/Reels/TikTok overrides, пересчёт 30 дней | unit tests + reclassification worker |
| Screenshots | active/all monitors, merge/separate, jitter/event/manual, blur, JPEG fallback q70, scaling/thumb, pHash per monitor, MinIO, gallery/lightbox/ZIP | backend tests + Windows CI/manual |
| Video | WHIP/WHEP, RTSP fallback, 720p/1080p profiles, hardware H.264→x264, no audio, on-demand/always/scheduled/trigger, indicator, wall 16, archive, 0.5–8×, seek/skip-idle/clip/pin | API tests + MediaMTX/Windows acceptance stand |
| Video storage | fMP4/5 мин на shared volume, worker index в `stream_segments`, MinIO copy, scoped protected playback, retention/pinned ranges | unit/API + Docker acceptance stand |
| HR | editable types, mass range, attachment validation, approval, holidays, fixed/shift/flexible/individual schedules with history, auto late/early/absence | backend tests + UI build |
| Colors/thresholds | schemes, patterns, scoped thresholds, CSS variables across UI, audit | backend tests + UI build |
| Reports | 8 reports, plan/online/active bases, grouping/filtering, CSV/XLSX/PDF, presets, cron e-mail jobs | backend tests |
| Roles/security | Argon2id, rotating JWT cookies, TOTP admin, lockout, backend scopes/IDOR, upload magic bytes, rate limit, security headers, RFC7807, TLS overlay | 50 backend tests + production validation |
| Operations | one-command Docker Compose, TimescaleDB continuous aggregates 1m/5m/1h/1d, Redis, MinIO, MediaMTX, Prometheus/Grafana/Loki, health/readiness/metrics, backup/restore | YAML/shell/OpenAPI static gate + Docker stand |
| Windows delivery | .NET 8 service/session agent, watchdog/RDP/proxy/TLS pin/logs/diagnostics/update, WiX MSI `/qn`, FFmpeg included, Authenticode sign/verify, canary | GitHub Actions `windows-latest` + signed release stand |
| Load | simulator 1–500 agents, parallel batches/heartbeats, p50/p95/max output | run on target stand for 15 min |

## Автоматический quality gate

```bash
pytest -q backend/tests
npm --prefix web run build
python -m compileall -q backend/app backend/tests scripts
sh -n install.sh scripts/*.sh
```

Локально подтверждены 50 backend-тестов, TypeScript/Vite production build, 98 OpenAPI paths, parsing Compose/CI YAML и shell syntax. В текущем macOS-окружении нет Docker, .NET SDK и PowerShell, поэтому Linux integration, Windows/MSI и аппаратные SLA выполняются GitHub Actions и на приёмочном стенде по `ACCEPTANCE_TEST_PLAN.md`.
