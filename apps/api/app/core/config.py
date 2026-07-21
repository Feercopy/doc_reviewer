from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    app_secret_key: str = Field(
        default="test-secret-key-for-local-development",
        alias="APP_SECRET_KEY",
    )
    database_url: str = Field(
        default="sqlite+pysqlite:///./gate_challenger.db",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    storage_root: Path = Field(
        default=Path("./storage"),
        alias="STORAGE_ROOT",
    )
    public_api_base_url: str = Field(
        default="http://localhost:8000",
        alias="PUBLIC_API_BASE_URL",
    )
    cors_allow_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,http://localhost:3100,http://127.0.0.1:3100",
        alias="CORS_ALLOW_ORIGINS",
    )
    hermes_enabled: bool = Field(default=False, alias="HERMES_ENABLED")
    hermes_mode: str = Field(default="http", alias="HERMES_MODE")
    hermes_http_url: str = Field(
        default="http://127.0.0.1:8787",
        alias="HERMES_HTTP_URL",
    )
    outbound_proxy_url: str | None = Field(default=None, alias="OUTBOUND_PROXY_URL")
    no_proxy: str = Field(
        default="localhost,127.0.0.1,::1,postgres,redis,api,worker,web",
        alias="NO_PROXY",
    )
    gate_challenger_source_path: str = Field(
        default="/external/gate-challenger",
        alias="GATE_CHALLENGER_SOURCE_PATH",
    )
    gate2_benchmark_dir: Path = Field(
        default=Path("/external/gate-challenger/benchmark"),
        alias="GATE2_BENCHMARK_DIR",
    )
    devils_advocate_source_path: str = Field(
        default="/external/devils-advocate",
        alias="DEVILS_ADVOCATE_SOURCE_PATH",
    )
    skill_source_snapshot_mode: str | None = Field(default=None, alias="SKILL_SOURCE_SNAPSHOT_MODE")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def cors_allow_origins(settings: Settings | None = None) -> list[str]:
    value = (settings or get_settings()).cors_allow_origins
    return [origin.strip() for origin in value.split(",") if origin.strip()]


def default_skill_source_snapshot_mode(settings: Settings | None = None) -> str:
    current_settings = settings or get_settings()
    configured_mode = (current_settings.skill_source_snapshot_mode or "").strip()
    if configured_mode:
        return configured_mode
    if current_settings.app_env == "development":
        return "development_current"
    return "production_latest"
