"""Application configuration, loaded from environment variables (prefix ``GEO_``)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GEO_", env_file=".env", extra="ignore")

    app_name: str = "Geospatial File Measurement API"
    app_version: str = "1.0.0"

    database_path: Path = Path("data/geospatial.db")

    # Upload limits
    max_upload_bytes: int = 50 * 1024 * 1024
    max_zip_entries: int = 200
    max_zip_uncompressed_bytes: int = 200 * 1024 * 1024
    max_features: int = 100_000

    # Measurement pagination
    default_page_size: int = 1000
    max_page_size: int = 10_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
