import os
from datetime import timezone, timedelta
from pydantic import field_validator
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

    @field_validator("master_admin", "api_port", mode="before")
    @classmethod
    def _blank_int_to_default(cls, v, info):
        """Treat a blank env value as 'unset' so it falls back to the default.

        Writing `MASTER_ADMIN=` in .env otherwise raises pydantic's int_parsing
        error at import time, which crash-loops the container with no obvious
        cause. .env.example used to ship exactly that line, so following the
        documented setup produced a server that would not boot.

        The default is looked up per field rather than hardcoded, since this
        guards both master_admin (0) and api_port (5000).
        """
        if isinstance(v, str) and not v.strip():
            return cls.model_fields[info.field_name].default
        return v

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
