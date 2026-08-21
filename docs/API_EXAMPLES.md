# API

OpenAPI 3.1 доступна администратору на `/api/docs` и `/api/openapi.json`.

```http
POST /api/v1/agent/register
Content-Type: application/json

{"installation_token":"…","hostname":"PC-01","machine_guid":"…","os_version":"Windows 11","agent_version":"1.0.0"}
```

Heartbeat: `POST /api/v1/agent/heartbeat` с `Authorization: Bearer`. Батчи — `/api/v1/agent/activity/batch`, поддерживается gzip и идемпотентность `event_uuid`.

```bash
curl --cookie cookies.txt https://monitoring.company.local/api/v1/presence
curl --cookie cookies.txt 'https://monitoring.company.local/api/v1/timeline?from=2026-08-21T00:00:00Z&to=2026-08-22T00:00:00Z'
```

Ошибки — `application/problem+json`: `type`, `title`, `status`, `detail`, `instance`.
