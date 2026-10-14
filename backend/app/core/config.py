from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_SECRET_KEY = "dev-insecure-secret-key-change-me-in-production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Sekkotsuin API"
    environment: str = "local"

    database_url: str = "postgresql+asyncpg://app:app@localhost:5432/sekkotsuin"

    # JWT
    # 本番では必ず 32 文字以上のランダム値を設定する（例: openssl rand -hex 32）
    secret_key: str = DEV_SECRET_KEY
    access_token_expire_minutes: int = 60 * 12
    jwt_algorithm: str = "HS256"

    # CORS（カンマ区切り）
    cors_origins: str = "http://localhost:3000"

    # 院のローカルタイムゾーン（予約枠の計算に使用）
    timezone: str = "Asia/Tokyo"

    # 問診URLの有効期限（日）
    intake_token_expire_days: int = 14

    @model_validator(mode="after")
    def _check_secret(self) -> "Settings":
        if self.environment != "local" and (
            self.secret_key == DEV_SECRET_KEY or len(self.secret_key) < 32
        ):
            raise ValueError("SECRET_KEY に32文字以上のランダム値を設定してください。")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
