# Архитектура

```mermaid
flowchart LR
  SA[Session Agent\nWinAPI / Screenshots / FFmpeg] -->|Named Pipe| WS[Windows Service\nSQLite + file queues]
  WS -->|HTTPS gzip batches| NG[nginx TLS]
  SA -->|WHIP / RTSP fallback| MTX[MediaMTX]
  NG --> API[FastAPI]
  NG --> WEB[React SPA]
  API --> PG[(PostgreSQL 16)]
  API --> REDIS[(Redis 7)]
  API --> MINIO[(MinIO private bucket)]
  API --> MTX
  WORKER[Background worker] --> PG
  WORKER --> MINIO
  PROM[Prometheus] --> API
  PROM --> MTX
  GRAF[Grafana] --> PROM
  GRAF --> LOKI[Loki]
```

Служба работает от `LocalSystem`, хранит device token через DPAPI и запускает Session Agent отдельно в каждой локальной/RDP-сессии через `CreateProcessAsUser`. Session Agent всегда показывает tray-иконку, собирает метаданные активного окна и только количественные счётчики ввода, делает снимки и запускает FFmpeg по разрешённой политике.

Очередь активности — SQLite, 7 суток/500 МБ; очередь снимков — файлы, 1 ГБ. Повторы исключаются по `event_uuid`, снимки дедуплицируются по perceptual hash.

PostgreSQL хранит оргструктуру, события, расписания, роли, аудит и индексы времени. MinIO хранит снимки, вложения, отчёты, MSI и диагностику. MediaMTX пишет fMP4 и публикует WHIP/WHEP/HLS. Redis отвечает за presence TTL, rate limit и pub/sub.

```mermaid
erDiagram
  DEPARTMENTS ||--o{ EMPLOYEES : contains
  EMPLOYEES ||--o{ DEVICES : owns
  DEVICES ||--o{ WINDOWS_ACCOUNTS : identifies
  EMPLOYEES ||--o{ ACTIVITY_EVENTS : produces
  CATEGORIES ||--o{ RULES : classifies
  ACTIVITY_EVENTS ||--o{ SCREENSHOTS : anchors
  EMPLOYEES ||--o{ STREAM_SESSIONS : records
  STREAM_SESSIONS ||--o{ STREAM_SEGMENTS : contains
  EMPLOYEES ||--o{ ABSENCES : has
  SCHEDULES ||--o{ SCHEDULE_ASSIGNMENTS : assigned
  USERS ||--o{ AUDIT_LOG : acts
```

Миграции `infra/postgres/002…017` идемпотентны и выполняются контейнером `migrate` до readiness API. TimescaleDB хранит write-through hypertable `activity_samples` и continuous aggregates 1 мин / 5 мин / 1 ч / 1 день, не ломая транзакционные связи исходных событий. `worker` запускает дисциплину, рассылки, ретеншен, переклассификацию, видеополитики, индексирует фактические fMP4-файлы MediaMTX в `stream_segments` и синхронизирует завершённые/изменившиеся сегменты в MinIO.
