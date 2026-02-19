import os
from datetime import timezone, timedelta
from pydantic_settings import BaseSettings, SettingsConfigDict

# UTC+7 timezone (e.g., Bangkok, Jakarta, Novosibirsk)
TZ_UTC7 = timezone(timedelta(hours=7))


class Settings(BaseSettings):
    # Telegram
    telegram_bot_token: str = ""

    # Database
    database_url: str = "/data/gravitymon.db"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 5000

    # Optional API token for webhook auth
    api_token: str = ""

    # Comma-separated Telegram chat_ids allowed to use the bot (empty = allow all)
    allowed_users: str = ""

    # Master admin user ID (can manage whitelist via bot commands)
    master_admin: int = 0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
