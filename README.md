# Workforce Monitoring

Корпоративная система учёта рабочего времени по ТЗ версии 1.0 от 19.08.2026. ManicTime использован как UX-референс, но не является зависимостью.

## Состав

- `backend/` — FastAPI, PostgreSQL, Redis, фоновые задачи, отчёты и аудит;
- `web/` — React/TypeScript: online, Canvas-таймлайн, карточки, снимки, live/архив, календарь, отчёты и админка;
- `agent/` — .NET 8 Windows Service + видимый Session Agent;
- `installer/` — WiX MSI с тихой установкой и восстановлением службы;
- `infra/` — nginx/TLS, MediaMTX, MinIO, Prometheus, Grafana, Loki;
- `scripts/` — миграции, бэкап/восстановление, эмулятор до 500 агентов.

## Production-запуск на Ubuntu 22.04/24.04

```bash
WORKFORCE_TLS_NAME=monitoring.company.local ./install.sh
```

Скрипт проверит Docker Compose v2, создаст `.env` с уникальными секретами, выпустит временный self-signed TLS и запустит стек. Для production замените сертификат в `infra/tls/` сертификатом корпоративного УЦ или Let's Encrypt.

После первого входа удалите `BOOTSTRAP_ADMIN_PASSWORD` из `.env`. Для `superadmin` и `admin` TOTP обязателен.

Локальный стенд:

```bash
cp .env.example .env
# Для localhost: APP_ENV=development, AUTH_COOKIE_SECURE=false,
# MEDIAMTX_PUBLISH_URL=http://localhost:8080/webrtc
docker compose up --build -d
```

Интерфейс: `http://localhost:8080`; readiness: `/api/v1/ready`; OpenAPI: `/api/docs` после входа администратором.

## Проверки

```bash
python3 -m pip install -e './backend[dev]'
pytest -q backend/tests
cd web && npm ci && npm run build
dotnet test agent/Workforce.Agent.Shared.Tests/Workforce.Agent.Shared.Tests.csproj -c Release
```

Windows-проекты и MSI собираются в GitHub Actions на `windows-latest`.

## Команды

```bash
make up
make logs
make monitoring
make backup
make restore FILE=backups/postgres-YYYYMMDD.dump
make simulate TOKEN=<INSTALLATION_TOKEN>
```

## Документация

- [Администратор](docs/ADMIN_GUIDE.md)
- [Руководитель и HR](docs/USER_GUIDE.md)
- [Сотрудник](docs/EMPLOYEE_GUIDE.md)
- [Массовая установка](docs/MASS_DEPLOYMENT.md)
- [Сборка Windows-агента](docs/AGENT_BUILD.md)
- [Архитектура](docs/ARCHITECTURE.md)
- [Безопасность](docs/SECURITY.md)
- [Персональные данные](docs/PRIVACY_DATA.md)
- [API](docs/API_EXAMPLES.md)
- [Приёмка](docs/ACCEPTANCE_TEST_PLAN.md)
- [Матрица соответствия ТЗ](docs/TRACEABILITY.md)
- [Сторонние компоненты](docs/THIRD_PARTY.md)
