# Безопасность

- TLS 1.2/1.3, HSTS, DTLS-SRTP; public playback MediaMTX закрыт.
- Device token через installation token, peppered hash, DPAPI и отзыв.
- Argon2id; access 15 мин, refresh 14 дней с ротацией/reuse detection; lockout; TOTP администраторов.
- Permission + employee scope на backend; IDOR-тесты; same-origin mutations и HttpOnly/Secure cookies.
- Rate limit 60/min агент, 300/min web; gzip bomb limit; upload size/MIME/magic.
- MinIO не публикуется. Медиа/диагностика — через авторизованные API; live-ключ случайный.
- Append-only DB audit с пользователем, сотрудником, IP и user-agent.
- Батч ≤5000, interval/overlap validation, clock skew >5 мин маркируется.
- MSI update требует SHA-256 и доверенную Authenticode-подпись.
- Production отклоняет development-секреты и insecure cookie.

До production: ротация секретов, корпоративный TLS/code-signing, SCA/container scan, внешний ASVS L2 review, DAST, firewall review и тест restore. Секреты рекомендуется перенести в Docker secrets/secret manager.
