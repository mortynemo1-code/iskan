# Backend

FastAPI-сервис первого вертикального среза.

## Локальный запуск

Нужны PostgreSQL 16 и Redis 7, после чего:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e './backend[dev]'
uvicorn app.main:app --app-dir backend --reload
```

Переменные окружения описаны в корневом `.env.example`. SQL-схема первого
среза находится в `infra/postgres/init.sql`.

## Начальный API

- `POST /api/v1/agent/register`
- `POST /api/v1/agent/heartbeat`
- `GET /api/v1/agent/config` — ETag/304;
- `POST /api/v1/agent/events` — системные события и tamper;
- `POST /api/v1/agent/activity/batch`
- `GET /api/v1/presence`
- `GET /api/v1/timeline?from=&to=`
- `WS /api/v1/ws/presence`
- `GET /api/v1/health`

Список presence временно открыт для разработки. До пилотного развёртывания он
будет закрыт JWT-аутентификацией и permission `timeline:view`.

События активного приложения классифицируются серверным rules engine. Первое
совпавшее правило по `priority` задаёт `PRODUCTIVE`, `NEUTRAL` или
`UNPRODUCTIVE`; состояния `IDLE`, `LOCKED` и `BREAK` не переопределяются.
