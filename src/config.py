from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # PostgreSQL
    database_url: str = "postgresql+asyncpg://payment_user:payment_pass@localhost:5432/payment_db"

    # RabbitMQ
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    # API Key
    api_key: str = "test-api-key-change-in-production"

    # Webhook
    webhook_hmac_secret: str = "webhook-secret-change-in-production"
    webhook_timeout: int = 10

    # SSRF protection
    ssrf_allow_private: bool = False

    # Logging
    log_level: str = "INFO"


settings = Settings()