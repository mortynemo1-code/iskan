# Windows Agent

Агент разделён на процессы согласно ТЗ:

- `Workforce.Agent` — Windows Service: регистрация, heartbeat, SQLite-очередь,
  повторные попытки, отправка батчей, конфигурация и watchdog;
- `Workforce.SessionAgent` — видимый tray-процесс в пользовательской сессии:
  активное окно, idle, lock/unlock и режим «Личное время»;
- `Workforce.Agent.Shared` — локальный контракт и агрегация событий.

Session Agent передаёт данные службе через named pipe. Токен устройства остаётся
в службе, хранится в `%ProgramData%/WorkforceMonitoring/device.dat` и защищён
Windows DPAPI. Очередь находится в `activity-queue.db`, хранит данные до 7 дней
и ограничена объёмом 500 МБ.

Служба перечисляет активные локальные и RDP-сессии через Windows Terminal
Services API. Для каждой сессии запускается ровно один Session Agent; проверка и
перезапуск выполняются каждые 10 секунд.

Конфигурация загружается с `/api/v1/agent/config` с поддержкой ETag, атомарно
сохраняется в `%ProgramData%/WorkforceMonitoring/agent-config.json` и применяется
Session Agent без перезапуска. В браузерах Chrome, Edge, Firefox, Yandex,
Vivaldi и Opera через UI Automation читаются только домен и путь; query-параметры
не сохраняются.

Для сборки требуется Windows и .NET 8 SDK:

```powershell
dotnet restore .\Workforce.Agent\Workforce.Agent.csproj
dotnet build .\Workforce.Agent\Workforce.Agent.csproj -c Release
dotnet build .\Workforce.SessionAgent\Workforce.SessionAgent.csproj -c Release
dotnet test .\Workforce.Agent.Shared.Tests\Workforce.Agent.Shared.Tests.csproj
```

Перед запуском задайте `Agent__ServerUrl` и `Agent__InstallationToken` через
переменные окружения или `appsettings.json`. Разместите
`Workforce.SessionAgent.exe` рядом со службой либо задайте абсолютный
`Agent__SessionAgentPath`. Tray-иконка не имеет команды скрытия или выхода, а
окно «Что собирает система» доступно всегда.
