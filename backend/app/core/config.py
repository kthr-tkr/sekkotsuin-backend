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
    patient_token_expire_minutes: int = 60 * 24 * 7
    jwt_algorithm: str = "HS256"

    # CORS（カンマ区切り）
    cors_origins: str = "http://localhost:3000"

    # 院のローカルタイムゾーン（予約枠の計算に使用）
    timezone: str = "Asia/Tokyo"

    # 問診URLの有効期限（日）
    intake_token_expire_days: int = 14

    # アップロードファイル（署名画像・姿勢写真など）の保存先と、署名付きURLの有効期限
    media_dir: str = "media"
    file_url_expire_seconds: int = 60 * 30
    max_upload_bytes: int = 10 * 1024 * 1024
    max_audio_bytes: int = 25 * 1024 * 1024  # OpenAI の文字起こし API の上限

    # 患者向け画面のベース URL（通知のリンクに使う）
    public_app_url: str = "http://localhost:3000"

    # 通知
    # メール: "smtp" | "console"（送らずに送信記録だけ残す）| "disabled"
    email_provider: str = "console"
    email_from: str = "no-reply@example.com"
    smtp_host: str = "localhost"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    # SMS: "twilio" | "console" | "disabled"
    sms_provider: str = "console"
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_number: str = ""

    # AI: "openai" | "fake"（開発・テスト用の固定応答）| "disabled"
    ai_provider: str = "fake"
    openai_api_key: str = ""
    openai_stt_model: str = "gpt-4o-mini-transcribe"
    openai_model: str = "gpt-4o-mini"
    openai_vision_model: str = "gpt-4o-mini"
    # 概算コスト（円）。料金改定時は環境変数で上書きする
    ai_cost_yen_per_audio_minute: float = 0.5
    ai_cost_yen_per_1k_input_tokens: float = 0.025
    ai_cost_yen_per_1k_output_tokens: float = 0.1

    @model_validator(mode="after")
    def _check_secret(self) -> "Settings":
        if self.environment != "local" and (
            self.secret_key == DEV_SECRET_KEY or len(self.secret_key) < 32
        ):
            raise ValueError("SECRET_KEY に32文字以上のランダム値を設定してください。")
        if self.ai_provider not in ("openai", "fake", "disabled"):
            raise ValueError("AI_PROVIDER は openai / fake / disabled のいずれかです。")
        if self.environment != "local" and self.ai_provider == "fake":
            raise ValueError("本番環境では AI_PROVIDER に openai か disabled を設定してください。")
        if self.email_provider not in ("smtp", "console", "disabled"):
            raise ValueError("EMAIL_PROVIDER は smtp / console / disabled のいずれかです。")
        if self.sms_provider not in ("twilio", "console", "disabled"):
            raise ValueError("SMS_PROVIDER は twilio / console / disabled のいずれかです。")
        if self.sms_provider == "twilio" and not (
            self.twilio_account_sid and self.twilio_auth_token and self.twilio_from_number
        ):
            raise ValueError("SMS_PROVIDER=twilio のときは TWILIO_* の設定が必要です。")
        if self.ai_provider == "openai" and not self.openai_api_key:
            raise ValueError("AI_PROVIDER=openai のときは OPENAI_API_KEY が必要です。")
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
