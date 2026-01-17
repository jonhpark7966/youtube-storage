"""Server configuration."""

from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Server
    api_host: str = "127.0.0.1"
    api_port: int = 32500

    # Paths
    videos_dir: Path = Path("/home/jonhpark/workspace/youtube-storage/videos")
    process_script: Path = Path("/home/jonhpark/workspace/youtube-storage/scripts/process_video.py")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()
