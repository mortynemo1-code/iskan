from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://workforce:change-me@localhost:5432/workforce"
    redis_url: str = "redis://localhost:6379/0"
    installation_token: str = "development-installation-token"
    device_token_pepper: str = "development-device-token-pepper"
    presence_ttl_seconds: int = 90
    heartbeat_interval_seconds: int = 30
    jwt_secret: str = "development-jwt-secret-change-me"
    jwt_issuer: str = "workforce-monitoring"
    access_token_minutes: int = 15
    refresh_token_days: int = 14
    auth_cookie_secure: bool = False
    bootstrap_admin_login: str | None = None
    bootstrap_admin_password: str | None = None
    bootstrap_admin_name: str = "Системный администратор"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin-change-me"
    minio_bucket: str = "workforce-media"
    minio_secure: bool = False
    mediamtx_internal_url: str = "http://mediamtx:9997"
    mediamtx_publish_url: str = "http://mediamtx:8889"
    mediamtx_rtsp_publish_url: str = "rtsp://mediamtx:8554"
    mediamtx_playback_url: str = "http://mediamtx:9996"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "workforce-monitoring@localhost"
    smtp_starttls: bool = True
    video_recording_root: str = "/recordings"
    storage_high_watermark_percent: int = 85
    run_background_workers: bool = True

    def validate_runtime(self) -> None:
        if self.app_env.lower() != "production": return
        insecure = {"development-installation-token", "development-device-token-pepper", "development-jwt-secret-change-me", "change-me"}
        values = {self.installation_token, self.device_token_pepper, self.jwt_secret}
        if values & insecure or any(len(value) < 32 for value in values):
            raise RuntimeError("Production secrets must be unique and at least 32 characters")
        if not self.auth_cookie_secure: raise RuntimeError("AUTH_COOKIE_SECURE must be true in production")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
