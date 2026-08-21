# Сторонние компоненты

Решение использует PostgreSQL/TimescaleDB, Redis, MinIO, MediaMTX, nginx, Prometheus, Grafana, Loki, React, FastAPI, .NET, NAudio и FFmpeg. Их лицензии не заменяются лицензией данного проекта.

Windows MSI включает предоставленный при сборке `ffmpeg.exe`. Ответственный за релиз обязан выбрать сборку FFmpeg, разрешённую политикой заказчика, сохранить её исходный URL, версию, SHA-256 и комплект license notices. CI использует пакет Chocolatey только для воспроизводимой тестовой сборки; production-релиз рекомендуется собирать с утверждённым бинарником через `FFMPEG_PATH`.

Пример:

```powershell
$env:FFMPEG_PATH = "C:\approved-tools\ffmpeg.exe"
./installer/build.ps1 -Version 1.0.0 -Sign -CertificateThumbprint <SHA1>
```
