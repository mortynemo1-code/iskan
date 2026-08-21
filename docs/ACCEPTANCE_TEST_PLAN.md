# Приёмочные испытания

CI: Python tests, TypeScript production build, .NET tests, self-contained publish и WiX MSI. Нагрузка: `scripts/simulate_agents.py --agents 100 --duration 3600 --workers 40`; ingest p95 ≤200 мс, таймлайн ≤1,5 с/≥30 FPS. Повторить 500 агентов.

## Ручная матрица

1. MSI `/qn TOKEN SERVER`, GPO/Intune, reboot, recovery, tamper.
2. Consent/tray/disclosure; break; lock; suspend/resume/shutdown; RDP и второй Windows-account/карантин.
3. Offline 2 часа → идемпотентная дозагрузка; queue limits; proxy/TLS pin.
4. Word, Shorts, media без ввода, retrospective idle, counts без содержания.
5. Снимки, jitter, multi-monitor, dedup, private blur, manual, ZIP/audit.
6. Live ≤3 с/≤2 с, indicator, wall 16, policy stop, archive/clip/pin/gap/retention.
7. Mass absence, attachment, workflow, late/early/absence drafts и влияние на отчёт.
8. Цвет/threshold без reload; scoped override; rule test/reclassification.
9. Восемь отчётов, CSV/XLSX/PDF, e-mail schedule/journal.
10. Export/delete employee, IDOR, 2FA/lockout/refresh reuse, rate limit, spoofed upload, append-only audit.
11. Disk/service alerts, backup restore, signed canary update 5% → 100%.

Нагрузка: `python scripts/simulate_agents.py --installation-token TOKEN --agents 500 --workers 80 --duration 900`. После завершения скрипт печатает `count`, `p50`, `p95` и `max` отдельно для регистрации, batch ingest и heartbeat; результат прикладывается к протоколу.

Фиксируются стенд/версия/время, фактическое значение, доказательство, PASS/FAIL и дефект. Обучение и юридические документы подписывает заказчик.
