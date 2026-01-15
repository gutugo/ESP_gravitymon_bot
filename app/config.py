import os
from pydantic_settings import BaseSettings


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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
