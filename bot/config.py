"""Bot configuration."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Bot settings loaded from environment variables."""

    # Discord
    discord_token: str = ""
    allowed_channel_id: int = 0  # 0 means allow all channels

    # API
    api_base_url: str = "http://127.0.0.1:32500"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
