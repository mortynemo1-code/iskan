# Массовая установка Windows-агента

Windows 10 1809+ / Windows 11 x64. MSI должен быть подписан доверенным сертификатом.

```powershell
msiexec /i Workforce.Agent.Installer.msi /qn /norestart `
  TOKEN="<installation-token>" SERVER="https://monitoring.company.local"
```

MSI устанавливает `WorkforceMonitoringAgent` от LocalSystem, автозапуск/восстановление, Session Agent и защищённый ProgramData. Удаление — только администратором.

GPO: Computer Configuration → Software Settings → Software installation. `TOKEN`/`SERVER` передавайте MST или startup script с ACL Domain Computers.

Intune: Line-of-business app; uninstall `msiexec /x {ProductCode} /qn`; detection — служба или `HKLM\Software\WorkforceMonitoring\Installed=1`.

Для self-signed TLS установите корневой сертификат либо задайте `Agent__ServerCertificateSha256`. Системный proxy используется автоматически; явный: `Agent__ProxyUrl`, `Agent__ProxyUsername`, `Agent__ProxyPassword`.

Production MSI подпишите сертификатом организации: `./installer/build.ps1 -Version 1.0.0 -Sign -CertificateThumbprint <SHA1>`. Скрипт использует SHA-256, RFC 3161 timestamp и сразу проверяет Authenticode. Закрытый ключ не хранится в репозитории.

Проверка: служба Running, tray в каждой активной/RDP-сессии, устройство в админке, после подтверждения приходят heartbeat и события.
