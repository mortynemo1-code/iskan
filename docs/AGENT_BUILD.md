# Сборка Windows-агента

Как получить установочный MSI-пакет агента — от нуля до файла, готового к раскатке на рабочие места.

## Что собираем

На выходе — один файл `WorkforceAgent.msi`. Внутри три компонента:

- **Windows Service** (`Workforce.Agent.exe`) — работает от `LocalSystem`, копит события в локальной SQLite-очереди и отправляет их на сервер;
- **Session Agent** (`Workforce.SessionAgent.exe`) — запускается в каждой пользовательской сессии, показывает иконку в трее, снимает скриншоты и метаданные активного окна;
- **ffmpeg.exe** — нужен агенту для записи видео по политике.

## Главное ограничение

> **Не пытайтесь собрать на сервере.** Сервер `94.41.21.238` работает под Linux, и агент там собрать невозможно. Это не вопрос установки .NET SDK.

Причины лежат в самих проектах:

- `Workforce.SessionAgent` использует `System.Windows.Automation` и WinForms — это Windows Desktop SDK, под Linux его не существует;
- `Workforce.Agent.Shared.Tests` ссылается на SessionAgent, поэтому под Linux не пройдут и тесты;
- `installer/build.ps1` требует PowerShell, `ffmpeg.exe` и WiX — всё только под Windows.

Поэтому в `.github/workflows/ci.yml` задание `windows-agent` выполняется на раннере `windows-latest`. Это спроектированный путь сборки, и машина с Windows для него не нужна — всё делает GitHub.

## Способ A. Через GitHub Actions

Основной способ. Занимает около трёх минут.

### 1. Подключиться к серверу

Все команды выполняются там — на сервере уже настроен `gh`, авторизованный под учётной записью `mortynemo1-code`.

На своём компьютере:

```bash
ssh -p 100 its@94.41.21.238
```

### 2. Перейти в проект и проверить ветку

Рабочая ветка — `claude/employee-monitoring-architecture-jjgyvd`. Убедитесь, что находитесь именно на ней и нет незакоммиченных правок.

На сервере:

```bash
cd ~/iskan && git status --short --branch
```

### 3. Запустить сборку

Отдельной кнопки нет: workflow стартует от любого пуша в репозиторий.

На сервере:

```bash
git push origin claude/employee-monitoring-architecture-jjgyvd
```

Если коммитов нет, а пересобрать нужно — перезапустите последний прогон:

```bash
gh run rerun
```

### 4. Дождаться результата

Команда покажет прогресс по шагам и завершится вместе с прогоном.

На сервере:

```bash
gh run watch
```

Если прогон покраснел — смотрите раздел «Если сборка упала». Полный лог ошибок:

```bash
gh run view --log-failed
```

### 5. Скачать MSI на сервер

Готовый пакет лежит в артефакте `workforce-agent-msi`.

На сервере:

```bash
gh run download --name workforce-agent-msi --dir ~/agent-msi
```

```bash
ls -la ~/agent-msi
```

### 6. Забрать файл к себе

Выполняется **на своём компьютере**, а не на сервере — иначе файл просто скопируется сам в себя.

```bash
scp -P 100 -r its@94.41.21.238:~/agent-msi ./
```

## Способ B. На машине с Windows

Нужен, если доступа к GitHub Actions нет или требуется отладить сборку локально. Подойдёт Windows 10, 11 или Windows Server.

### 1. Поставить зависимости

.NET SDK версии 8.0 и ffmpeg. WiX подтянется сам при первой сборке — он подключён как SDK-пакет `WixToolset.Sdk`.

PowerShell от администратора:

```powershell
winget install Microsoft.DotNet.SDK.8
```

```powershell
choco install ffmpeg -y
```

После установки закройте и откройте терминал заново, иначе `dotnet` и `ffmpeg` не окажутся в `PATH`.

### 2. Получить исходники

```powershell
git clone https://github.com/mortynemo1-code/iskan.git
```

```powershell
cd iskan
git checkout claude/employee-monitoring-architecture-jjgyvd
```

### 3. Прогнать тесты

Быстрая проверка, что код вообще компилируется, до долгой сборки установщика.

```powershell
dotnet test agent/Workforce.Agent.Shared.Tests/Workforce.Agent.Shared.Tests.csproj -c Release
```

### 4. Собрать MSI

Скрипт публикует оба исполняемых файла, кладёт рядом `ffmpeg.exe` и собирает пакет.

```powershell
powershell -ExecutionPolicy Bypass -File .\installer\build.ps1
```

Если ffmpeg не в `PATH`, укажите путь явно:

```powershell
$env:FFMPEG_PATH = "C:\ffmpeg\bin\ffmpeg.exe"
```

Готовый файл появится в `installer\Workforce.Agent.Installer\bin\Release`.

## Подпись установщика

> **Сейчас не настроено.** Секреты подписи в репозитории не заданы, поэтому MSI собирается неподписанным. Шаги подписи в workflow при этом молча пропускаются — сборка выглядит успешной.

Неподписанный пакет на рабочих местах вызовет предупреждение SmartScreen, а корпоративные политики установки ПО могут заблокировать его полностью. Для боевой раскатки подпись обязательна.

Чтобы включить, добавьте два секрета в настройках репозитория — **Settings → Secrets and variables → Actions**:

| Секрет | Содержимое |
| --- | --- |
| `WINDOWS_SIGNING_CERT_BASE64` | PFX-сертификат, закодированный в base64 |
| `WINDOWS_SIGNING_CERT_PASSWORD` | пароль от этого PFX |

Как только оба появятся, следующая сборка подпишет MSI автоматически — правок в коде не требуется.

## Если сборка упала

Сначала посмотрите, на каком шаге. Ниже — ошибки, которые уже встречались, и что они значат.

| Сообщение | Причина и что делать |
| --- | --- |
| `recent account payments have failed or your spending limit needs to be increased` | GitHub не запускает раннеры из-за биллинга. К коду отношения не имеет. Лечится в **Settings → Billing & plans** учётной записи `mortynemo1-code`. Признак — задание падает за 4–10 секунд, не начав работу. |
| `The name 'AutomationElement' could not be found` | Проект не видит сборки UI Automation. Исправлено: в `Workforce.SessionAgent.csproj` добавлен `FrameworkReference` на профиль `Microsoft.WindowsDesktop.App.WPF`. Не заменяйте это на `UseWPF` — он подменяет набор неявных `using` и ломает весь `System.IO`. |
| `The name 'Path' / 'File' / 'Directory' does not exist` | Как раз последствие `UseWPF`. Если увидели — значит кто-то вернул этот флаг обратно. |
| `The name 'AudioSessionState' does not exist` | В NAudio 2.x тип лежит в `NAudio.CoreAudioApi.Interfaces`. Исправлено добавлением `using`. |
| `'IServiceCollection' does not contain a definition for 'AddHttpClient'` | Не хватало пакета `Microsoft.Extensions.Http`. Исправлено в `Workforce.Agent.csproj`. |
| `WIX0150: Undefined preprocessor variable` | Пути публикации не доходили до препроцессора WiX. Исправлено: они добавлены в `DefineConstants` в `.wixproj`, после объявления самих путей — MSBuild вычисляет свойства по порядку. |
| `WIX0368: The Component/@Guid attribute's value '*' is not valid` | В одном компоненте лежали два версионированных файла. Исправлено: `ffmpeg.exe` вынесен в отдельный компонент. |

### Порядок шагов задания

Помогает быстро понять, где остановились.

| Шаг | Что делает |
| --- | --- |
| `dotnet test` | компилирует Shared и SessionAgent, гоняет модульные тесты |
| `dotnet publish` ×2 | публикует службу и Session Agent под `win-x64` |
| `choco install ffmpeg` | ставит ffmpeg на раннер |
| `build.ps1` | собирает MSI через WiX |
| `upload-artifact` | выкладывает готовый пакет |

## Установка на рабочие места

Тихая установка без диалогов — подробности в [MASS_DEPLOYMENT.md](MASS_DEPLOYMENT.md):

```
msiexec /i WorkforceAgent.msi /qn ^
  SERVER_URL=https://monitoring.company.local ^
  INSTALLATION_TOKEN=<токен>
```

Токен установки — это значение `INSTALLATION_TOKEN` из файла `.env` на сервере. Он общий для всех устанавливаемых агентов и сверяется сервером напрямую при регистрации, а не выпускается в админке. После регистрации агент получает собственный device-токен и `INSTALLATION_TOKEN` больше не использует.

Посмотреть текущее значение на сервере:

```bash
grep INSTALLATION_TOKEN ~/iskan/.env
```

> Обращайтесь с ним как с паролем: кто знает токен, тот может зарегистрировать устройство. Не передавайте его вместе с MSI по открытым каналам.

**Проверка после установки.** Служба `WorkforceMonitoringAgent` должна быть в состоянии *Running*, а в трее пользователя — появиться иконка Session Agent. Устройство появится в админке в списке на одобрение.

---

Репозиторий: `github.com/mortynemo1-code/iskan` · ветка `claude/employee-monitoring-architecture-jjgyvd`
